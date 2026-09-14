/**
 * The house style, as components. Nothing else in the app sets a colour.
 *
 * Every value here comes from src/tokens.ts, which is generated from
 * design/tokens.json by tools/tokens.py - the same source the web CSS and the
 * Flutter constants come from. A hex literal anywhere else in this app is the
 * bug that file exists to prevent: the brief calls a colour that differs
 * between clients a bug rather than an inconsistency.
 *
 * GLASS, ON ANDROID, HONESTLY
 * ---------------------------
 * The design's raised surfaces are glass: a tint at a given alpha over a blur.
 * A plain React Native View cannot blur what is behind it, and pretending
 * otherwise by adding a blur library would put a third rendering path in the
 * app for a visual effect.
 *
 * So Surface composes the tint at its step's alpha over the ambient ground,
 * and the blur is not faked. What that loses is the softening; what it keeps
 * is the depth order, which is the part that carries meaning - a surface over
 * CONTENT is denser than one over the GROUND, and that is exactly what the
 * five alphas encode. The `blur` number is still exported and still read here,
 * so a real blur slots in behind this one component when there is one.
 */

import React from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from 'react-native';

import { ambient, core, depth, glass, metric, pen, radius, space, tinted, type } from './tokens';

type Depth = keyof typeof depth;
type Tint = keyof typeof tinted;

// ---------------------------------------------------------------------------
// the ground
// ---------------------------------------------------------------------------

/**
 * The app ground: the machine's shell, ruled with a graticule.
 *
 * NOT DECORATION. The glass above it is translucent, and a flat ground under
 * translucent panels reads as one grey slab - the ambient washes and the grid
 * are what give every surface something to pick up. The web ground does the
 * same thing with a radial-gradient stack and the token source carries the
 * washes for both.
 */
/**
 * How many rings each ambient wash is drawn from.
 *
 * A View has one background colour and no gradient, so a wash drawn as a
 * single ellipse is a hard-edged disc - which is what the first version did
 * and it looked like a sticker rather than light. Nested circles at a low
 * alpha each composite into a real radial falloff: the middle has every ring
 * over it, the edge has one.
 *
 * Twelve is where it stops being visibly banded on a 1260px screen. More is
 * more views to lay out for no visible gain.
 */
const WASH_RINGS = 12;

export function Ground({ children }: { children?: React.ReactNode }) {
  const { width, height } = useWindowDimensions();

  return (
    <View style={styles.ground}>
      <Graticule />
      {ambient.map((wash, index) => {
        // `at` and `size` are fractions of the box - CSS's two
        // radial-gradient percentages, carried through the token source so
        // both clients place the light identically.
        const w = wash.size[0] * width;
        const h = wash.size[1] * height;
        const [r, g, b] = wash.rgb;

        // The per-ring alpha that accumulates to the token's own alpha at the
        // centre: 1 - (1 - a)^n = A. Solved rather than eyeballed, so the
        // wash is as bright as the design says and not as bright as looked
        // about right.
        const each = 1 - Math.pow(1 - wash.alpha, 1 / WASH_RINGS);

        return (
          <View
            key={index}
            pointerEvents="none"
            style={{
              position: 'absolute',
              left: wash.at[0] * width - w / 2,
              top: wash.at[1] * height - h / 2,
              width: w,
              height: h,
              alignItems: 'center',
              justifyContent: 'center',
            }}>
            {Array.from({ length: WASH_RINGS }, (_, ring) => {
              const scale = 1 - ring / WASH_RINGS;
              return (
                <View
                  key={ring}
                  style={{
                    position: 'absolute',
                    width: w * scale,
                    height: h * scale,
                    borderRadius: Math.max(w, h),
                    backgroundColor: `rgba(${r}, ${g}, ${b}, ${each})`,
                  }}
                />
              );
            })}
          </View>
        );
      })}
      <View style={styles.groundContent}>{children}</View>
    </View>
  );
}

/** The ruled graticule, at the brief's own grid value. */
function Graticule() {
  const step = space.room;
  const lines: React.ReactNode[] = [];
  for (let i = 1; i <= 40; i += 1) {
    lines.push(
      <View key={`h${i}`} style={[styles.rule, { top: i * step, height: 1, left: 0, right: 0 }]} />,
    );
    lines.push(
      <View key={`v${i}`} style={[styles.rule, { left: i * step, width: 1, top: 0, bottom: 0 }]} />,
    );
  }
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      {lines}
    </View>
  );
}

// ---------------------------------------------------------------------------
// surfaces
// ---------------------------------------------------------------------------

export function Surface({
  step = 'panel',
  style,
  children,
}: {
  step?: Depth;
  style?: StyleProp<ViewStyle>;
  children?: React.ReactNode;
}) {
  const it = depth[step];
  return (
    <View
      style={[
        {
          backgroundColor: glass.tint(it.alpha),
          borderRadius: it.radius,
          borderWidth: StyleSheet.hairlineWidth,
          borderColor: glass.hairline(),
        },
        style,
      ]}>
      {children}
    </View>
  );
}

/** Tinted glass: keeps its hue, and the border takes the tint. */
export function Tinted({
  tint,
  style,
  children,
}: {
  tint: Tint;
  style?: StyleProp<ViewStyle>;
  children?: React.ReactNode;
}) {
  const it = tinted[tint];
  const [r, g, b] = it.rgb;
  return (
    <View
      style={[
        {
          backgroundColor: `rgba(${r}, ${g}, ${b}, ${it.alpha})`,
          borderRadius: radius.control,
          borderWidth: StyleSheet.hairlineWidth,
          borderColor: `rgba(${r}, ${g}, ${b}, ${it.borderAlpha})`,
        },
        style,
      ]}>
      {children}
    </View>
  );
}

// ---------------------------------------------------------------------------
// ink
// ---------------------------------------------------------------------------

/**
 * Ink is never translucent.
 *
 * Design handoff section 6: glass is the surface under a value, never the
 * value. Text, numbers, callouts and check marks are full opacity always - so
 * these components have no alpha to set, on purpose.
 */
export function Mono({
  size = 'body',
  weight = 'regular',
  color = core.screen,
  style,
  children,
  numberOfLines,
}: {
  size?: keyof typeof type.size;
  weight?: keyof typeof type.weight;
  color?: string;
  style?: StyleProp<TextStyle>;
  children?: React.ReactNode;
  numberOfLines?: number;
}) {
  return (
    <Text
      numberOfLines={numberOfLines}
      style={[
        {
          fontFamily: type.mono,
          fontSize: type.size[size],
          fontWeight: type.weight[weight],
          color,
        },
        style,
      ]}>
      {children}
    </Text>
  );
}

export function Prose({
  size = 'reading',
  color = core.screen,
  style,
  children,
}: {
  size?: keyof typeof type.size;
  color?: string;
  style?: StyleProp<TextStyle>;
  children?: React.ReactNode;
}) {
  return (
    <Text
      style={[
        {
          fontFamily: type.prose,
          fontSize: type.size[size],
          color,
          lineHeight: type.size[size] * 1.45,
        },
        style,
      ]}>
      {children}
    </Text>
  );
}

// ---------------------------------------------------------------------------
// controls
// ---------------------------------------------------------------------------

/**
 * A button, at the brief's tap floor.
 *
 * `metric.tap` is 44 and it is pinned in the token source rather than chosen
 * here so neither client invents its own. A control smaller than that is not
 * a style disagreement, it is a thing people miss.
 */
export function Button({
  label,
  onPress,
  primary = false,
  disabled = false,
  style,
}: {
  label: string;
  onPress: () => void;
  primary?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: primary ? core.phosphor : glass.tint(depth.well.alpha),
          borderColor: primary ? core.phosphor : glass.hairline(),
          opacity: disabled ? 0.4 : pressed ? 0.8 : 1,
        },
        style,
      ]}>
      <Mono
        size="label"
        weight="medium"
        color={primary ? core.case : core.screen}
        numberOfLines={1}>
        {label}
      </Mono>
    </Pressable>
  );
}

/** A row of mutually exclusive choices. The app's only tab control. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  style,
}: {
  options: readonly T[];
  value: T;
  onChange: (next: T) => void;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <Surface step="well" style={[styles.segmented, style]}>
      {options.map((option) => {
        const active = option === value;
        return (
          <Pressable
            key={option}
            onPress={() => onChange(option)}
            style={[
              styles.segment,
              active && { backgroundColor: glass.tint(depth.pill.alpha) },
            ]}>
            <Mono
              size="label"
              weight={active ? 'medium' : 'regular'}
              color={active ? core.phosphor : core.dim}>
              {option}
            </Mono>
          </Pressable>
        );
      })}
    </Surface>
  );
}

/**
 * A label and its value on one line, the value hard right.
 *
 * The app's most repeated shape: every measurement, every parameter readout,
 * every line of the report's numbers. Written once so they line up.
 */
export function Row({
  label,
  value,
  valueColor = core.screen,
  style,
}: {
  label: string;
  value: string;
  valueColor?: string;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <View style={[styles.row, style]}>
      <Mono size="label" color={core.dim}>
        {label}
      </Mono>
      <Mono size="label" weight="medium" color={valueColor}>
        {value}
      </Mono>
    </View>
  );
}

/**
 * A status line that says its state in words as well as in colour.
 *
 * Brief 6.7 forbids colour-only status, and this is where that rule is kept
 * for the whole app: the pen is chosen here and a word always goes with it.
 */
export function Verdict({
  state,
  text,
  style,
}: {
  state: 'pass' | 'warn' | 'fail' | 'waiting';
  text: string;
  style?: StyleProp<ViewStyle>;
}) {
  const marks = { pass: 'OK', warn: '!', fail: 'X', waiting: '...' } as const;
  const colours = {
    pass: pen.pass,
    warn: pen.warn,
    fail: pen.fail,
    waiting: core.dim,
  } as const;

  return (
    <View style={[styles.verdict, style]}>
      <View style={[styles.mark, { borderColor: colours[state] }]}>
        <Mono size="micro" weight="bold" color={colours[state]}>
          {marks[state]}
        </Mono>
      </View>
      <Mono size="label" color={colours[state]} style={styles.verdictText} numberOfLines={2}>
        {text}
      </Mono>
    </View>
  );
}

/** Something went wrong, said in a sentence, with a way out. */
export function Problem({
  text,
  actionLabel,
  onAction,
}: {
  text: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    // A NEUTRAL SURFACE WITH A FAIL BORDER, not a tinted one. The token source
    // has three tinted glasses - warn, ref, active - and no fail, and adding a
    // fourth here would give the native client a colour the web client does
    // not have, which is the drift the shared source exists to stop. The pen
    // carries the state, and the word beside it carries it for anyone who
    // cannot see the colour.
    <Surface step="card" style={[styles.problem, { borderColor: pen.fail }]}>
      <Verdict state="fail" text="that did not work" />
      <Prose size="body" color={core.screen}>
        {text}
      </Prose>
      {actionLabel && onAction ? (
        <Button label={actionLabel} onPress={onAction} style={styles.problemAction} />
      ) : null}
    </Surface>
  );
}

export function Panel({
  title,
  children,
  style,
}: {
  title?: string;
  children?: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <Surface step="panel" style={[styles.panel, style]}>
      {title ? (
        <Mono size="micro" color={core.dim} style={styles.panelTitle}>
          {title}
        </Mono>
      ) : null}
      {children}
    </Surface>
  );
}

export { ScrollView };

const styles = StyleSheet.create({
  ground: {
    flex: 1,
    backgroundColor: core.case,
  },
  groundContent: {
    flex: 1,
  },
  rule: {
    position: 'absolute',
    backgroundColor: core.grid,
  },
  button: {
    minHeight: metric.tap,
    paddingHorizontal: space.wide,
    borderRadius: radius.control,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
  },
  segmented: {
    flexDirection: 'row',
    padding: space.hair,
    gap: space.hair,
  },
  segment: {
    flex: 1,
    minHeight: metric.tap - space.snug,
    borderRadius: radius.panel,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.snug,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: space.tight,
    gap: space.base,
  },
  verdict: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  mark: {
    minWidth: 20,
    height: 16,
    paddingHorizontal: space.tight,
    borderWidth: 1,
    borderRadius: radius.edge,
    alignItems: 'center',
    justifyContent: 'center',
  },
  verdictText: {
    flex: 1,
  },
  problem: {
    padding: space.base,
    gap: space.base,
  },
  problemAction: {
    alignSelf: 'flex-start',
  },
  panel: {
    padding: space.base,
    gap: space.snug,
  },
  panelTitle: {
    letterSpacing: 0.5,
  },
});
