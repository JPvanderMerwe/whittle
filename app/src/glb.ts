/**
 * A GLB reader for the geometry whittle sends, and nothing else.
 *
 * WHY NOT three's GLTFLoader
 * --------------------------
 * Because this repo has already paid twice for a viewer that draws nothing.
 * `model_viewer_plus` rendered an empty box on the phone with no error in
 * logcat and no exception in Dart, which is why the Flutter client ships a
 * WebView and a vendored copy of model-viewer. GLTFLoader is a large example
 * module that expects a DOM for textures and a TextDecoder for its JSON
 * chunk; under Hermes either can be missing, and the failure mode is the same
 * silent blank.
 *
 * What the server actually sends is narrow and known, because it is written
 * by trimesh's Scene.export and measured in tests/test_glb.js against a real
 * exported file:
 *
 *     one buffer, embedded as the BIN chunk   (no external URIs)
 *     primitives in mode 4                    (triangles)
 *     POSITION as VEC3 float                  (no textures, no materials)
 *     indices as SCALAR ubyte/ushort/uint
 *     normals usually absent                  (computed on arrival)
 *
 * So this parses that, refuses anything else by name, and is fifty lines
 * somebody can read in one sitting. Anything wider - animation, textures,
 * Draco - is not a smaller version of this problem and should not be bolted
 * on here; it needs the real loader and a device that has been proven to draw
 * its output.
 */

/** One drawable lump: a node's primitive, already placed in world space. */
export interface Primitive {
  positions: Float32Array;
  indices: Uint32Array;
  /** Column-major 4x4, the node's world transform. three takes this order. */
  matrix: number[];
}

const MAGIC = 0x46546c67; // 'glTF'
const JSON_CHUNK = 0x4e4f534a;
const BIN_CHUNK = 0x004e4942;

const COMPONENT_BYTES: Record<number, number> = {
  5120: 1, // byte
  5121: 1, // unsigned byte
  5122: 2, // short
  5123: 2, // unsigned short
  5125: 4, // unsigned int
  5126: 4, // float
};

const COMPONENTS: Record<string, number> = {
  SCALAR: 1,
  VEC2: 2,
  VEC3: 3,
  VEC4: 4,
  MAT4: 16,
};

/**
 * Decode the JSON chunk without assuming a TextDecoder exists.
 *
 * Hermes has had TextDecoder for a while and may well have it here, but a
 * viewport that blanks on one runtime and not another is the exact bug this
 * file was written to avoid. glTF's JSON chunk is UTF-8 and in practice ASCII
 * for these files - accessor names, "POSITION", numbers - so the fallback
 * handles the multi-byte case properly rather than mangling it quietly.
 */
function decodeUtf8(bytes: Uint8Array): string {
  const Decoder = (globalThis as any).TextDecoder;
  if (typeof Decoder === 'function') {
    return new Decoder('utf-8').decode(bytes);
  }

  let out = '';
  for (let i = 0; i < bytes.length; ) {
    const b = bytes[i];
    let code: number;
    if (b < 0x80) {
      code = b;
      i += 1;
    } else if (b < 0xe0) {
      code = ((b & 0x1f) << 6) | (bytes[i + 1] & 0x3f);
      i += 2;
    } else if (b < 0xf0) {
      code =
        ((b & 0x0f) << 12) | ((bytes[i + 1] & 0x3f) << 6) | (bytes[i + 2] & 0x3f);
      i += 3;
    } else {
      code =
        ((b & 0x07) << 18) |
        ((bytes[i + 1] & 0x3f) << 12) |
        ((bytes[i + 2] & 0x3f) << 6) |
        (bytes[i + 3] & 0x3f);
      i += 4;
    }
    if (code > 0xffff) {
      code -= 0x10000;
      out += String.fromCharCode(0xd800 + (code >> 10), 0xdc00 + (code & 0x3ff));
    } else {
      out += String.fromCharCode(code);
    }
  }
  return out;
}

function identity(): number[] {
  return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
}

/** a * b, both column-major, the way three and glTF write them. */
function multiply(a: number[], b: number[]): number[] {
  const out = new Array(16).fill(0);
  for (let col = 0; col < 4; col += 1) {
    for (let row = 0; row < 4; row += 1) {
      let sum = 0;
      for (let k = 0; k < 4; k += 1) {
        sum += a[k * 4 + row] * b[col * 4 + k];
      }
      out[col * 4 + row] = sum;
    }
  }
  return out;
}

/**
 * A node's own transform: `matrix` if it has one, otherwise T * R * S.
 *
 * glTF says a node has either a matrix or the three components, never both,
 * and that the components compose in that order. trimesh writes a matrix, but
 * a file from anywhere else may not, and getting this wrong puts a body in
 * the wrong place rather than failing - the quietest kind of wrong.
 */
function localMatrix(node: any): number[] {
  if (Array.isArray(node.matrix) && node.matrix.length === 16) {
    return node.matrix.slice();
  }

  const [tx, ty, tz] = node.translation ?? [0, 0, 0];
  const [qx, qy, qz, qw] = node.rotation ?? [0, 0, 0, 1];
  const [sx, sy, sz] = node.scale ?? [1, 1, 1];

  const x2 = qx + qx;
  const y2 = qy + qy;
  const z2 = qz + qz;
  const xx = qx * x2;
  const xy = qx * y2;
  const xz = qx * z2;
  const yy = qy * y2;
  const yz = qy * z2;
  const zz = qz * z2;
  const wx = qw * x2;
  const wy = qw * y2;
  const wz = qw * z2;

  return [
    (1 - (yy + zz)) * sx, (xy + wz) * sx, (xz - wy) * sx, 0,
    (xy - wz) * sy, (1 - (xx + zz)) * sy, (yz + wx) * sy, 0,
    (xz + wy) * sz, (yz - wx) * sz, (1 - (xx + yy)) * sz, 0,
    tx, ty, tz, 1,
  ];
}

/**
 * Read one accessor out of the binary chunk.
 *
 * BYTE STRIDE IS HONOURED. Interleaved attributes are legal glTF and reading
 * them as tightly packed gives a mesh made of noise - which looks like a
 * geometry bug rather than a parsing one, and is where an afternoon goes.
 */
function readAccessor(gltf: any, bin: Uint8Array, index: number): Float64Array {
  const accessor = gltf.accessors[index];
  const size = COMPONENTS[accessor.type];
  const bytes = COMPONENT_BYTES[accessor.componentType];
  if (!size || !bytes) {
    throw new Error(
      `accessor ${index} is ${accessor.type}/${accessor.componentType}, ` +
        'which whittle does not send and this reader does not decode',
    );
  }

  const out = new Float64Array(accessor.count * size);
  if (accessor.bufferView === undefined) {
    return out; // legal glTF: an accessor with no view reads as zeros
  }

  const view = gltf.bufferViews[accessor.bufferView];
  const start = (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0);
  const stride = view.byteStride ?? size * bytes;
  const data = new DataView(bin.buffer, bin.byteOffset, bin.byteLength);

  for (let i = 0; i < accessor.count; i += 1) {
    for (let c = 0; c < size; c += 1) {
      const at = start + i * stride + c * bytes;
      let value: number;
      switch (accessor.componentType) {
        case 5120: value = data.getInt8(at); break;
        case 5121: value = data.getUint8(at); break;
        case 5122: value = data.getInt16(at, true); break;
        case 5123: value = data.getUint16(at, true); break;
        case 5125: value = data.getUint32(at, true); break;
        default: value = data.getFloat32(at, true); break;
      }
      out[i * size + c] = value;
    }
  }
  return out;
}

/**
 * Every triangle in a GLB, placed in world space.
 *
 * Throws with a sentence rather than returning an empty list: a viewport that
 * silently draws nothing is the failure this whole file exists to rule out,
 * so an unreadable file has to be loud.
 */
export function readGlb(buffer: ArrayBuffer): Primitive[] {
  const header = new DataView(buffer);
  if (buffer.byteLength < 12 || header.getUint32(0, true) !== MAGIC) {
    throw new Error('that is not a GLB - the first four bytes are not "glTF"');
  }
  if (header.getUint32(4, true) !== 2) {
    throw new Error(`GLB version ${header.getUint32(4, true)}, and this reads version 2`);
  }

  let gltf: any = null;
  let bin: Uint8Array = new Uint8Array(0);

  let at = 12;
  while (at + 8 <= buffer.byteLength) {
    const length = header.getUint32(at, true);
    const kind = header.getUint32(at + 4, true);
    const body = new Uint8Array(buffer, at + 8, length);
    if (kind === JSON_CHUNK) {
      gltf = JSON.parse(decodeUtf8(body));
    } else if (kind === BIN_CHUNK) {
      bin = body;
    }
    at += 8 + length + ((4 - (length % 4)) % 4);
  }

  if (!gltf) {
    throw new Error('the GLB has no JSON chunk');
  }
  if (gltf.buffers?.some((b: any) => b.uri)) {
    throw new Error(
      'this GLB keeps its geometry in a separate file, and whittle only sends ' +
        'self-contained ones',
    );
  }

  const out: Primitive[] = [];
  const scene = gltf.scenes?.[gltf.scene ?? 0];
  const roots: number[] = scene?.nodes ?? gltf.nodes?.map((_: any, i: number) => i) ?? [];

  const walk = (index: number, parent: number[]) => {
    const node = gltf.nodes[index];
    if (!node) return;
    const matrix = multiply(parent, localMatrix(node));

    if (node.mesh !== undefined) {
      for (const primitive of gltf.meshes[node.mesh].primitives ?? []) {
        // MODE 4 ONLY. Strips and fans are legal and whittle never writes one;
        // drawing them as separate triangles would fold the model in on
        // itself, so they are refused rather than mis-drawn.
        const mode = primitive.mode ?? 4;
        if (mode !== 4) {
          throw new Error(`primitive mode ${mode} is not triangles`);
        }
        const position = primitive.attributes?.POSITION;
        if (position === undefined) continue;

        const points = readAccessor(gltf, bin, position);
        const positions = Float32Array.from(points);

        let indices: Uint32Array;
        if (primitive.indices !== undefined) {
          indices = Uint32Array.from(readAccessor(gltf, bin, primitive.indices));
        } else {
          indices = new Uint32Array(positions.length / 3);
          for (let i = 0; i < indices.length; i += 1) indices[i] = i;
        }
        out.push({ positions, indices, matrix });
      }
    }

    for (const child of node.children ?? []) walk(child, matrix);
  };

  for (const root of roots) walk(root, identity());

  if (out.length === 0) {
    throw new Error('the GLB parsed but holds no triangles');
  }
  return out;
}
