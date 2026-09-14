/**
 * The rig: whittle's own loader, and the only one in the app.
 *
 * A solid turning slowly on a plinth while a visor line sweeps down it and
 * reads off its dimensions. It is the brand mark in motion - an isometric
 * solid with a quarter section cut away, lit in amber - and it is doing the
 * thing the product does: measuring something.
 *
 * WHY NOT A SPINNER
 * -----------------
 * Because a spinner says "wait" and nothing else, and everything this app
 * waits for takes long enough that "wait" is not an answer. A generate runs
 * minutes. An ingest runs repair, then the gate, then a thickness measurement
 * over every triangle. The rig says which of those is happening, in the
 * caption, and the visor pass gives the eye something with a rhythm so the
 * wait has a shape.
 *
 * THE ROTATION IS REAL 3D. Eight corners of a box, turned about the vertical
 * axis and projected - not a 2D shape spun round, which reads as a sticker on
 * a turntable. It costs twelve lines of arithmetic a frame and it is the
 * difference between the thing looking like an object and looking like a GIF.
 *
 * WHAT DRIVES WHAT, AND WHY
 * -------------------------
 * The visor and the plinth pulse run on Animated with the native driver, so
 * they keep moving while JavaScript is busy - and JavaScript IS busy here,
 * parsing a GLB or waiting on a fetch. The wireframe needs its vertices
 * recomputed each frame, which only JS can do, so it runs at a deliberately
 * modest rate: a body turning slightly unevenly still reads as a body, where a
 * visor line that stutters reads as a broken app.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Easing, StyleSheet, View } from 'react-native';
import Svg, { Circle, Line, Path, Polygon } from 'react-native-svg';

import { core, pen, space } from './tokens';
import { Mono } from './ui';

/**
 * Frames per second for the wireframe.
 *
 * 24 on purpose. The visor is native-driven and smooth; the body only has to
 * read as turning, and every frame here is a JS re-render competing with the
 * work being waited on. Faster costs the thing it is covering for.
 */
const TURN_FPS = 24;

/** One full turn, in milliseconds. Slow: this is a machine, not a loading GIF. */
const TURN_MS = 5200;

/** One visor pass, top to bottom. */
const VISOR_MS = 1900;

interface Props {
  /** What is actually happening. One short line, lower case, no full stop. */
  caption?: string;
  /** 0..1 when there is a real fraction to show. Omit when there is not. */
  fraction?: number;
  /** Rendered size in dp. The layout inside scales from this. */
  size?: number;
}

/** A corner of the box, before it is turned. Unit cube, centred, y up on screen. */
const CORNERS: [number, number, number][] = [
  [-1, -1, -1], [1, -1, -1], [1, -1, 1], [-1, -1, 1],
  [-1, 1, -1], [1, 1, -1], [1, 1, 1], [-1, 1, 1],
];

/** Which corners are joined. Twelve edges of a box. */
const EDGES: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 0],
  [4, 5], [5, 6], [6, 7], [7, 4],
  [0, 4], [1, 5], [2, 6], [3, 7],
];

/**
 * The quarter that is cut away, as a face on the near-top corner.
 *
 * This is the recognisable half of the mark: a section view is the drafting
 * convention for showing what is inside a part, which is what the product
 * does. The exposed internal faces are lit in amber and everything else stays
 * a construction line.
 */
const CUT: number[] = [1, 2, 6, 5];

export function Rig({ caption, fraction, size = 132 }: Props) {
  const [angle, setAngle] = useState(0);
  const visor = useRef(new Animated.Value(0)).current;
  const glow = useRef(new Animated.Value(0)).current;

  // The body. A timer rather than Animated, because each frame needs new
  // vertex positions and only JS can compute those.
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => {
      setAngle((((Date.now() - started) % TURN_MS) / TURN_MS) * Math.PI * 2);
    }, 1000 / TURN_FPS);
    return () => clearInterval(timer);
  }, []);

  // The visor and the plinth. NATIVE DRIVER: these keep moving while the JS
  // thread is parsing a mesh, which is exactly when somebody is looking at it.
  useEffect(() => {
    const sweep = Animated.loop(
      Animated.timing(visor, {
        toValue: 1,
        duration: VISOR_MS,
        easing: Easing.inOut(Easing.cubic),
        useNativeDriver: true,
      }),
    );
    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(glow, {
          toValue: 1,
          duration: VISOR_MS,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true,
        }),
        Animated.timing(glow, {
          toValue: 0,
          duration: VISOR_MS,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true,
        }),
      ]),
    );
    sweep.start();
    pulse.start();
    return () => {
      sweep.stop();
      pulse.stop();
    };
  }, [glow, visor]);

  const view = useMemo(() => project(angle, size), [angle, size]);

  const plinth = size * 0.78;

  return (
    <View style={[styles.rig, { width: size, height: size + space.room }]}>
      <View style={{ width: size, height: size }}>
        <Svg width={size} height={size}>
          {/* The plinth the body stands on: the graticule, in one ellipse and
              two axes, so the object is standing on something rather than
              floating in a box. */}
          <Circle
            cx={size / 2}
            cy={size * 0.78}
            r={plinth / 2}
            stroke={pen.dim}
            strokeWidth={1}
            fill="none"
            opacity={0.55}
          />
          <Line
            x1={size / 2 - plinth / 2}
            y1={size * 0.78}
            x2={size / 2 + plinth / 2}
            y2={size * 0.78}
            stroke={pen.dim}
            strokeWidth={1}
            opacity={0.35}
          />

          {/* THE CUT FACE FIRST, so the wireframe draws over it rather than
              under. Amber, because that is what the mark does and it is the
              one thing in the app allowed to be lit. */}
          <Polygon
            points={CUT.map((i) => `${view.points[i][0]},${view.points[i][1]}`).join(' ')}
            fill={core.phosphor}
            fillOpacity={0.16}
            stroke={core.phosphor}
            strokeWidth={1.2}
          />

          {EDGES.map(([a, b], index) => (
            <Line
              key={index}
              x1={view.points[a][0]}
              y1={view.points[a][1]}
              x2={view.points[b][0]}
              y2={view.points[b][1]}
              stroke={pen.solid}
              strokeWidth={1.2}
              // BACK EDGES STAY VISIBLE AND FAINT. Hiding them would need a
              // depth sort for a shape that is deliberately a wireframe - and
              // seeing through it is what says "this is a drawing of a solid"
              // rather than "this is a solid".
              opacity={view.depth[a] + view.depth[b] > 0 ? 0.95 : 0.28}
            />
          ))}
        </Svg>

        {/* THE VISOR. One amber line crossing the whole frame, with a soft
            leading edge - the measuring pass. It is outside the Svg so it can
            be driven natively. */}
        <Animated.View
          pointerEvents="none"
          style={[
            styles.visor,
            {
              transform: [
                {
                  translateY: visor.interpolate({
                    inputRange: [0, 1],
                    outputRange: [size * 0.06, size * 0.94],
                  }),
                },
              ],
              opacity: visor.interpolate({
                // Fades in and out at the ends so it reads as a pass over the
                // object rather than a line that teleports back to the top.
                inputRange: [0, 0.12, 0.88, 1],
                outputRange: [0, 1, 1, 0],
              }),
            },
          ]}>
          <View style={[styles.visorLine, { width: size }]} />
          <View style={[styles.visorGlow, { width: size }]} />
        </Animated.View>
      </View>

      <View style={styles.caption}>
        {caption ? (
          <Animated.View style={{ opacity: glow.interpolate({
            // Breathing, not blinking: the caption never fully leaves, so the
            // words stay readable while still saying the machine is alive.
            inputRange: [0, 1],
            outputRange: [0.55, 1],
          }) }}>
            <Mono size="micro" color={core.dim}>
              {caption}
            </Mono>
          </Animated.View>
        ) : null}
        {fraction !== undefined ? (
          <View style={[styles.track, { width: size }]}>
            <View
              style={[
                styles.fill,
                { width: `${Math.max(0, Math.min(1, fraction)) * 100}%` },
              ]}
            />
          </View>
        ) : null}
      </View>
    </View>
  );
}

/**
 * Turn the box and flatten it onto the screen.
 *
 * Rotation about the vertical axis, then a fixed tilt so it is seen slightly
 * from above - the isometric three-quarter view every CAD program opens in,
 * and the angle the mark is drawn at. Perspective is deliberate and slight:
 * enough that the near face is bigger, not enough to look like a game.
 */
function project(angle: number, size: number): { points: [number, number][]; depth: number[] } {
  const TILT = 0.42;           // radians above the horizon
  const SPREAD = size * 0.23;  // half-width of the body on screen
  const DEPTH = 3.4;           // camera distance in body radii

  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const ct = Math.cos(TILT);
  const st = Math.sin(TILT);

  const points: [number, number][] = [];
  const depth: number[] = [];

  for (const [x, y, z] of CORNERS) {
    // about the vertical axis
    const rx = x * cos - z * sin;
    const rz = x * sin + z * cos;
    // then tilt the world down so we look at it from above
    const ry = y * ct - rz * st;
    const rd = y * st + rz * ct;

    const scale = DEPTH / (DEPTH + rd);
    points.push([
      size / 2 + rx * SPREAD * scale,
      size * 0.5 + ry * SPREAD * scale,
    ]);
    depth.push(-rd);
  }

  return { points, depth };
}

/**
 * The rig, centred in whatever space it is given, with the caption under it.
 *
 * Every wait in the app uses this rather than composing its own layout, so a
 * pause always looks the same wherever it happens.
 */
export function Waiting({
  caption,
  fraction,
  size,
  style,
}: Props & { style?: any }) {
  return (
    <View style={[styles.centre, style]}>
      <Rig caption={caption} fraction={fraction} size={size} />
    </View>
  );
}

const styles = StyleSheet.create({
  rig: {
    alignItems: 'center',
  },
  centre: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.base,
  },
  visor: {
    position: 'absolute',
    left: 0,
    top: 0,
  },
  visorLine: {
    height: 1,
    backgroundColor: core.phosphor,
  },
  visorGlow: {
    height: 8,
    backgroundColor: core.phosphor,
    opacity: 0.1,
  },
  caption: {
    marginTop: space.snug,
    alignItems: 'center',
    gap: space.tight,
  },
  track: {
    height: 2,
    backgroundColor: core.etch,
    borderRadius: 1,
    overflow: 'hidden',
  },
  fill: {
    height: 2,
    backgroundColor: core.phosphor,
  },
});
