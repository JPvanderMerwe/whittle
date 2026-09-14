/**
 * The 3D canvas: the model, the bed it stands on, and two fingers to look at it.
 *
 * THIS IS THE THIRD ATTEMPT AT A VIEWER ON THIS PROJECT, AND THE FIRST NATIVE
 * ONE. The Flutter client's own notes record that `model_viewer_plus` "drew
 * nothing, with no error in logcat and no exception in Dart", which is why it
 * ships a WebView and a vendored copy of model-viewer. That works and it is
 * two rendering stacks in a phone app.
 *
 * So this draws with three.js on an expo-gl context: the geometry is parsed by
 * src/glb.ts, which is tested against files the engine actually wrote, and
 * every step between the bytes and the screen is code in this repository. When
 * it draws nothing there is somewhere to look.
 *
 * Z IS UP. whittle is a CAD program and its models stand on z=0; three's default
 * camera has y up, and leaving it that way lays every model on its side. The
 * camera's `up` is set once, here, and the bed is the z=0 plane.
 */

import { GLView, type ExpoWebGLRenderingContext } from 'expo-gl';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { PanResponder, StyleSheet, View } from 'react-native';
import * as THREE from 'three';

import { readGlb } from './glb';
import { Waiting } from './Rig';
import { core, pen, radius, space } from './tokens';
import { Mono, Surface } from './ui';

/** Where the camera starts: looking down on the model from the front-right. */
const START = { azimuth: -Math.PI * 0.35, elevation: Math.PI * 0.22, zoom: 1.0 };

/** How far in and out two fingers may take it. */
const ZOOM = { min: 0.25, max: 8.0 };

/** Straight down would gimbal-lock the orbit, so it stops just short. */
const ELEVATION_LIMIT = Math.PI / 2 - 0.01;

interface Props {
  glb: ArrayBuffer | null;
  /** True when the geometry on screen is the proxy rather than the mesh. */
  simplified?: boolean;
  /** Said over the canvas when there is no geometry yet. */
  placeholder?: string;
}

/**
 * A three renderer over an expo-gl context.
 *
 * This is what `expo-three`'s Renderer does, and the reason it is inlined is
 * that it is a dozen lines: three only wants an object with a size and the
 * event methods it registers a context-loss handler on. A dependency whose job
 * is to construct one object, and which lags three's releases, is a dependency
 * that eventually breaks the app for no benefit.
 *
 * THE CONTEXT IS NOT PASSED IN, AND THAT IS THE WHOLE OF THIS FUNCTION.
 * ---------------------------------------------------------------------
 * The obvious spelling is `new WebGLRenderer({ canvas, context: gl })`, and on
 * the device it threw before drawing a single frame:
 *
 *     THREE.WebGLRenderer: WebGL 1 is not supported since r163.
 *
 * Which is not true of this context. three checks the context it is HANDED
 * with `context instanceof WebGLRenderingContext`, and in a browser a WebGL 2
 * context fails that test because the two classes are siblings. Under expo-gl
 * they are not: its context satisfies `instanceof WebGLRenderingContext` and
 * implements WebGL 2 as well, so a perfectly good context is refused by a
 * test that cannot tell them apart.
 *
 * So the context is not handed over. three is given a canvas whose getContext
 * returns it, takes its own `webgl2` path, and never runs the check. The
 * context is identical either way - what changes is which of three's branches
 * looks at it.
 *
 * Verified on the device: the version string is logged once on creation, and
 * it says WebGL 2.
 */
function makeRenderer(gl: ExpoWebGLRenderingContext): THREE.WebGLRenderer {
  const canvas = {
    width: gl.drawingBufferWidth,
    height: gl.drawingBufferHeight,
    clientWidth: gl.drawingBufferWidth,
    clientHeight: gl.drawingBufferHeight,
    style: {},
    addEventListener: () => {},
    removeEventListener: () => {},
    // EVERY contextName GETS THE SAME CONTEXT. three asks for 'webgl2'; there
    // is only one context here and it is the one to give back.
    getContext: () => gl,
  } as unknown as HTMLCanvasElement;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setSize(gl.drawingBufferWidth, gl.drawingBufferHeight, false);
  renderer.setClearColor(new THREE.Color(core.case), 1);
  return renderer;
}

/**
 * The bed: a ruled plane at z=0 so the model is standing on something.
 *
 * Sized from the model rather than from the printer, deliberately. The bed
 * dimensions are on the server and this is not a print preview - it is a
 * horizon, and one that is 220 mm wide under a 12 mm model is a horizon you
 * cannot see.
 */
function makeGround(size: number): THREE.Object3D {
  const group = new THREE.Group();
  const step = size / 10;
  const half = size / 2;

  const points: number[] = [];
  for (let i = -5; i <= 5; i += 1) {
    points.push(i * step, -half, 0, i * step, half, 0);
    points.push(-half, i * step, 0, half, i * step, 0);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
  group.add(
    new THREE.LineSegments(
      geometry,
      new THREE.LineBasicMaterial({ color: new THREE.Color(pen.dim) }),
    ),
  );
  return group;
}

/** The model, one mesh per primitive, flat-shaded in the printable pen. */
function makeModel(glb: ArrayBuffer): { object: THREE.Object3D; box: THREE.Box3 } {
  const group = new THREE.Group();

  for (const part of readGlb(glb)) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(part.positions, 3));
    geometry.setIndex(new THREE.BufferAttribute(part.indices, 1));
    // THE ENGINE SENDS NO NORMALS - trimesh's exporter writes POSITION and
    // indices and nothing else, which is measured in app/tests/glb.test.ts.
    // Without this every face renders unlit and the model is a silhouette.
    geometry.computeVertexNormals();

    const mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshPhongMaterial({
        color: new THREE.Color(pen.solid),
        flatShading: true,
        shininess: 12,
        // BOTH SIDES. A repaired import can still have a face wound the wrong
        // way, and a hole in the render that is not a hole in the mesh sends
        // somebody looking for a geometry fault that is not there.
        side: THREE.DoubleSide,
      }),
    );
    mesh.matrixAutoUpdate = false;
    mesh.matrix.fromArray(part.matrix);
    group.add(mesh);
  }

  const box = new THREE.Box3().setFromObject(group);
  return { object: group, box };
}

export function Viewport({ glb, simplified = false, placeholder }: Props) {
  const [failure, setFailure] = useState<string | null>(null);

  // Everything the render loop touches lives in refs: a re-render must not
  // rebuild the GL context, and the loop must not close over stale state.
  const scene = useRef<THREE.Scene | null>(null);
  const camera = useRef<THREE.PerspectiveCamera | null>(null);
  const renderer = useRef<THREE.WebGLRenderer | null>(null);
  const context = useRef<ExpoWebGLRenderingContext | null>(null);
  const model = useRef<THREE.Object3D | null>(null);
  const ground = useRef<THREE.Object3D | null>(null);

  const view = useRef({ ...START });
  const target = useRef(new THREE.Vector3());
  const span = useRef(100);
  const dirty = useRef(true);

  /** Put the camera where the orbit says, looking at the model's middle. */
  const place = useCallback(() => {
    const cam = camera.current;
    if (!cam) return;
    const { azimuth, elevation, zoom } = view.current;
    const distance = span.current * 2.2 * zoom;
    cam.position.set(
      target.current.x + distance * Math.cos(elevation) * Math.cos(azimuth),
      target.current.y + distance * Math.cos(elevation) * Math.sin(azimuth),
      target.current.z + distance * Math.sin(elevation),
    );
    cam.lookAt(target.current);
    // Near and far track the model: a 6 mm part and a 400 mm one cannot share
    // a clip range without one of them z-fighting or disappearing.
    cam.near = Math.max(0.01, distance / 100);
    cam.far = distance * 10 + span.current * 10;
    cam.updateProjectionMatrix();
    dirty.current = true;
  }, []);

  /** Swap in new geometry and frame it. */
  const show = useCallback(
    (bytes: ArrayBuffer | null) => {
      const world = scene.current;
      if (!world) return;

      for (const old of [model.current, ground.current]) {
        if (old) world.remove(old);
      }
      model.current = null;
      ground.current = null;

      if (!bytes) {
        dirty.current = true;
        return;
      }

      try {
        const { object, box } = makeModel(bytes);
        const size = box.getSize(new THREE.Vector3());
        span.current = Math.max(size.x, size.y, size.z) || 100;
        box.getCenter(target.current);

        ground.current = makeGround(span.current * 2.5);
        // The ground sits under the model, not through its middle.
        ground.current.position.set(target.current.x, target.current.y, box.min.z);

        world.add(object);
        world.add(ground.current);
        model.current = object;
        setFailure(null);
        place();
      } catch (error: any) {
        // LOUD, NOT BLANK. An unreadable preview is the exact failure this
        // viewport was rewritten to stop being silent about.
        setFailure(String(error?.message ?? error));
      }
    },
    [place],
  );

  const onContextCreate = useCallback(
    (gl: ExpoWebGLRenderingContext) => {
      context.current = gl;

      // NOTHING IN HERE MAY THROW. This callback runs on the native queue, so
      // an exception is a FATAL EXCEPTION in logcat and the app disappears -
      // which is how the WebGL 1 refusal above presented: not a blank
      // viewport, a dead app. A renderer that cannot be built is a message.
      try {
        renderer.current = makeRenderer(gl);
        console.log('[whittle] gl version:', gl.getParameter(gl.VERSION));
      } catch (error: any) {
        setFailure(String(error?.message ?? error));
        return;
      }

      const world = new THREE.Scene();
      world.background = new THREE.Color(core.case);

      // THREE LIGHTS, NOT ONE. A single light leaves every face pointing away
      // from it black, and a black face on a dark ground reads as a hole in
      // the model - which is a printability fault, so the render must not
      // invent one.
      world.add(new THREE.AmbientLight(new THREE.Color(core.screen), 0.45));
      const key = new THREE.DirectionalLight(new THREE.Color(core.screen), 1.5);
      key.position.set(1, -1, 2);
      world.add(key);
      const fill = new THREE.DirectionalLight(new THREE.Color(pen.ref), 0.35);
      fill.position.set(-1.5, 1, 0.5);
      world.add(fill);

      const cam = new THREE.PerspectiveCamera(
        38,
        gl.drawingBufferWidth / gl.drawingBufferHeight,
        0.1,
        5000,
      );
      cam.up.set(0, 0, 1); // Z UP. See the file header.

      scene.current = world;
      camera.current = cam;
      show(glb);
      place();

      const loop = () => {
        requestAnimationFrame(loop);
        // ONLY WHEN SOMETHING MOVED. A phone redrawing a still model at 60 fps
        // for an hour is a warm phone and a flat battery, and this viewport is
        // looked at for far longer than it is dragged.
        if (!dirty.current || !renderer.current) return;
        dirty.current = false;
        try {
          renderer.current.render(world, cam);
          gl.endFrameEXP();
        } catch (error: any) {
          // Same rule as above: a draw that fails says so once and stops,
          // rather than throwing sixty times a second off the native queue.
          dirty.current = false;
          setFailure(String(error?.message ?? error));
        }
      };
      loop();
    },
    [glb, place, show],
  );

  // New geometry from the server: swap it in without touching the context.
  useEffect(() => {
    if (scene.current) show(glb);
  }, [glb, show]);

  const gesture = useRef({ x: 0, y: 0, pinch: 0, zoom: 1 });
  const responder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: (event) => {
        const touches = event.nativeEvent.touches;
        gesture.current.x = touches[0]?.pageX ?? 0;
        gesture.current.y = touches[0]?.pageY ?? 0;
        gesture.current.pinch = 0;
        gesture.current.zoom = view.current.zoom;
      },
      onPanResponderMove: (event) => {
        const touches = event.nativeEvent.touches;

        if (touches.length >= 2) {
          // TWO FINGERS ZOOM. Measured against the distance at the moment the
          // second finger landed rather than against the last frame, so the
          // gesture does not drift as it goes.
          const dx = touches[0].pageX - touches[1].pageX;
          const dy = touches[0].pageY - touches[1].pageY;
          const spread = Math.hypot(dx, dy);
          if (gesture.current.pinch === 0) {
            gesture.current.pinch = spread;
            gesture.current.zoom = view.current.zoom;
            return;
          }
          const factor = gesture.current.pinch / Math.max(spread, 1);
          view.current.zoom = Math.min(
            ZOOM.max,
            Math.max(ZOOM.min, gesture.current.zoom * factor),
          );
          place();
          return;
        }

        const touch = touches[0];
        if (!touch) return;
        if (gesture.current.pinch !== 0) {
          // A finger lifted out of a pinch: restart the drag from here rather
          // than snapping the model round by the gap between the two.
          gesture.current.pinch = 0;
          gesture.current.x = touch.pageX;
          gesture.current.y = touch.pageY;
          return;
        }

        const dx = touch.pageX - gesture.current.x;
        const dy = touch.pageY - gesture.current.y;
        gesture.current.x = touch.pageX;
        gesture.current.y = touch.pageY;

        view.current.azimuth -= dx * 0.01;
        view.current.elevation = Math.min(
          ELEVATION_LIMIT,
          Math.max(-ELEVATION_LIMIT, view.current.elevation + dy * 0.01),
        );
        place();
      },
      onPanResponderRelease: () => {
        gesture.current.pinch = 0;
      },
    }),
  ).current;

  return (
    <View style={styles.frame} {...responder.panHandlers}>
      <GLView style={StyleSheet.absoluteFill} onContextCreate={onContextCreate} />

      {failure ? (
        <Surface step="pill" style={[styles.note, { borderColor: pen.fail }]}>
          <Mono size="micro" color={pen.fail}>
            {failure}
          </Mono>
        </Surface>
      ) : null}

      {!glb && !failure ? (
        // THE RIG STANDS IN FOR THE MODEL UNTIL THERE IS ONE. An empty dark
        // canvas and a word is indistinguishable from the viewport having
        // failed to draw - which on this project has happened twice - so the
        // wait has the same turning solid as every other wait in the app.
        <View style={StyleSheet.absoluteFill} pointerEvents="none">
          <Waiting caption={placeholder ?? 'waiting for geometry'} style={styles.fill} />
        </View>
      ) : null}

      {simplified ? (
        // SAY SO. The preview above a certain size is the proxy, and what gets
        // exported is the full mesh - the user should not have to work out why
        // the render and the file disagree.
        <Surface step="pill" style={styles.corner}>
          <Mono size="micro" color={core.dim}>
            simplified for the viewport
          </Mono>
        </Surface>
      ) : null}

      <Surface step="pill" style={styles.hint}>
        <Mono size="micro" color={core.dim}>
          drag to orbit  ·  pinch to zoom
        </Mono>
      </Surface>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    flex: 1,
    backgroundColor: core.case,
    borderRadius: radius.card,
    overflow: 'hidden',
  },
  note: {
    position: 'absolute',
    left: space.base,
    right: space.base,
    top: space.base,
    padding: space.snug,
  },
  corner: {
    position: 'absolute',
    right: space.base,
    bottom: space.base,
    paddingHorizontal: space.snug,
    paddingVertical: space.tight,
  },
  fill: {
    flex: 1,
  },
  hint: {
    position: 'absolute',
    left: space.base,
    bottom: space.base,
    paddingHorizontal: space.snug,
    paddingVertical: space.tight,
  },
});
