/**
 * The GLB reader, against files the engine actually wrote.
 *
 *     npm test
 *
 * Run under node's own test runner and its TypeScript stripping, so the app
 * needs no jest, no babel config and no second toolchain to prove the one
 * piece of the client that can silently draw nothing.
 *
 * Every expectation here comes from tools/glb_fixtures.py, which measured the
 * TRIMESH mesh rather than the exported file. That is the whole point: a
 * reader checked against a file it also wrote proves only that it is
 * self-consistent.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { readGlb, type Primitive } from '../src/glb.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, 'fixtures');

interface Case {
  name: string;
  file: string;
  bytes: number;
  triangles: number;
  vertices: number;
  min: [number, number, number];
  max: [number, number, number];
  centroid: [number, number, number];
  area_mm2: number;
}

const manifest = JSON.parse(
  readFileSync(join(FIXTURES, 'manifest.json'), 'utf8'),
) as { cases: Case[] };

function load(file: string): ArrayBuffer {
  const bytes = readFileSync(join(FIXTURES, file));
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

/** A point through a column-major 4x4, which is how glTF and three write one. */
function place(m: number[], x: number, y: number, z: number): [number, number, number] {
  return [
    m[0] * x + m[4] * y + m[8] * z + m[12],
    m[1] * x + m[5] * y + m[9] * z + m[13],
    m[2] * x + m[6] * y + m[10] * z + m[14],
  ];
}

/** Every vertex of every primitive, in world space. */
function worldPoints(parts: Primitive[]): [number, number, number][] {
  const out: [number, number, number][] = [];
  for (const part of parts) {
    for (let i = 0; i < part.positions.length; i += 3) {
      out.push(
        place(part.matrix, part.positions[i], part.positions[i + 1], part.positions[i + 2]),
      );
    }
  }
  return out;
}

function triangleCount(parts: Primitive[]): number {
  return parts.reduce((total, part) => total + part.indices.length / 3, 0);
}

/** Total surface area, which is the cheapest check that the WINDING is read right. */
function surfaceArea(parts: Primitive[]): number {
  let total = 0;
  for (const part of parts) {
    for (let i = 0; i < part.indices.length; i += 3) {
      const points = [0, 1, 2].map((k) => {
        const v = part.indices[i + k] * 3;
        return place(part.matrix, part.positions[v], part.positions[v + 1], part.positions[v + 2]);
      });
      const ax = points[1][0] - points[0][0];
      const ay = points[1][1] - points[0][1];
      const az = points[1][2] - points[0][2];
      const bx = points[2][0] - points[0][0];
      const by = points[2][1] - points[0][1];
      const bz = points[2][2] - points[0][2];
      const cx = ay * bz - az * by;
      const cy = az * bx - ax * bz;
      const cz = ax * by - ay * bx;
      total += Math.sqrt(cx * cx + cy * cy + cz * cz) / 2;
    }
  }
  return total;
}

for (const expected of manifest.cases) {
  test(`${expected.name}: every triangle arrives`, () => {
    const parts = readGlb(load(expected.file));
    assert.equal(triangleCount(parts), expected.triangles);
  });

  test(`${expected.name}: it lands where the engine measured it`, () => {
    // THE BOUNDS, NOT THE EXTENTS. A body 400 mm up the z axis has the same
    // extents as one at the origin, and the difference is the bug that put a
    // cut plane on the top face of the model.
    const points = worldPoints(readGlb(load(expected.file)));
    for (const axis of [0, 1, 2]) {
      const values = points.map((p) => p[axis]);
      assert.ok(
        Math.abs(Math.min(...values) - expected.min[axis]) < 1e-3,
        `axis ${axis} starts at ${Math.min(...values)}, engine says ${expected.min[axis]}`,
      );
      assert.ok(
        Math.abs(Math.max(...values) - expected.max[axis]) < 1e-3,
        `axis ${axis} ends at ${Math.max(...values)}, engine says ${expected.max[axis]}`,
      );
    }
  });

  test(`${expected.name}: the surface is the surface the engine measured`, () => {
    // A stride or index mistake still produces triangles and still produces a
    // plausible bounding box. It does not produce the right area.
    const area = surfaceArea(readGlb(load(expected.file)));
    const drift = Math.abs(area - expected.area_mm2) / expected.area_mm2;
    assert.ok(drift < 1e-4, `area ${area} mm2, engine measured ${expected.area_mm2} mm2`);
  });
}

test('two separate bodies stay separate', () => {
  // The product's own output after a cut. Welding them into one lump would
  // still draw correctly and would make "which piece is which" impossible.
  const parts = readGlb(load('two-bodies.glb'));
  const points = worldPoints(parts);
  const left = points.filter((p) => p[0] < 0);
  const right = points.filter((p) => p[0] > 0);
  assert.equal(left.length, 8);
  assert.equal(right.length, 8);
});

test('a file that is not a GLB says so rather than drawing nothing', () => {
  const notGlb = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]).buffer;
  assert.throws(() => readGlb(notGlb), /not a GLB/);
});

test('an empty buffer says so', () => {
  assert.throws(() => readGlb(new ArrayBuffer(0)), /not a GLB/);
});

test('the JSON chunk decodes without a TextDecoder', () => {
  // THE POINT OF THE FALLBACK. Hermes may or may not have TextDecoder, and a
  // viewport that blanks on one runtime and not another is the failure this
  // reader exists to rule out - so the path without it is exercised here
  // rather than discovered on a device.
  const real = (globalThis as any).TextDecoder;
  (globalThis as any).TextDecoder = undefined;
  try {
    const parts = readGlb(load('box.glb'));
    assert.equal(triangleCount(parts), 12);
  } finally {
    (globalThis as any).TextDecoder = real;
  }
});
