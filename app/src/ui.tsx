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

import { BlurView } from 'expo-blur';
import React from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
  type KeyboardTypeOptions,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from 'react-native';
import Svg, { Path, Rect } from 'react-native-svg';

import { ambient, core, depth, glass, metric, pen, radius, space, tinted, type } from './tokens';
import { Press } from './motion';

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
  flat = false,
  children,
}: {
  step?: Depth;
  style?: StyleProp<ViewStyle>;
  /**
   * Draw the fill without the blur.
   *
   * FOR LISTS, AND ONLY FOR LISTS. A blur is a real-time read of everything
   * behind the view, and a scrolling grid of forty cards is forty of them
   * being recomputed every frame. The gallery is the one place in this app
   * with that many surfaces on screen at once, and a gallery that stutters
   * is worse than one whose tiles are a shade flatter.
   */
  flat?: boolean;
  children?: React.ReactNode;
}) {
  const it = depth[step];
  const shell: StyleProp<ViewStyle> = {
    borderRadius: it.radius,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: glass.hairline(),
    overflow: 'hidden',
  };

  if (flat) {
    return (
      <View style={[shell, { backgroundColor: glass.tint(it.alpha) }, style]}>
        {children}
      </View>
    );
  }

  // THE BLUR THE TOKENS ALWAYS SPECIFIED.
  //
  // `depth` has carried a `blur` per step since it was written, and the
  // comment above it says "a view that builds its own blur is the bug this
  // module exists to prevent" - so the design always meant real glass, and
  // this component drew a flat translucent fill instead. On a dark ground
  // with a lit gradient behind it, the difference is the whole look: a fill
  // is a grey card, a blur picks up the light behind it and moves with the
  // content.
  //
  // THE TINT STAYS ON TOP OF THE BLUR rather than being replaced by it. The
  // blur alone is colourless and would let the ground's hue through
  // unchanged; the tint is what makes every surface in this app the same
  // material.
  return (
    <View style={[shell, style]}>
      <BlurView
        intensity={it.blur * 2.2}
        tint="dark"
        style={StyleSheet.absoluteFill}
        pointerEvents="none"
      />
      <View
        style={[StyleSheet.absoluteFill, { backgroundColor: glass.tint(it.alpha) }]}
        pointerEvents="none"
      />
      {/* THE LIGHT ON THE TOP EDGE. `glass.highlight` has been in the tokens
          from the start and nothing drew it: it is the one-pixel line that
          makes a pane read as a pane rather than as a rectangle. */}
      <View
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: StyleSheet.hairlineWidth,
          backgroundColor: glass.highlight(),
        }}
        pointerEvents="none"
      />
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
          fontFamily: type.prose,
          fontSize: type.size[size],
          fontWeight: type.weight[weight],
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
  // PRESSED IS A SCALE NOW, NOT A FADE. Fading a control on touch dims the
  // one thing a finger is covering; a small scale is felt at the edges,
  // where it can still be seen. See src/motion.tsx.
  return (
    <Press
      onPress={onPress}
      disabled={disabled}
      style={[
        styles.button,
        {
          // A DISABLED PRIMARY IS NOT A FADED ONE.
          //
          // This filled with phosphor and then dropped the whole control to
          // 0.4 opacity, which on the dark ground turns amber into a muddy
          // olive slab - and it is the largest object on the landing screen,
          // so the resting state of the app's front page was a button that
          // looks broken rather than one waiting for input.
          //
          // Unfilled instead, with the accent kept in the border and the
          // label: the same shape, clearly not yet pressable, and it becomes
          // solid the moment there is something to send. That transition is
          // now the thing that tells you the button is live.
          backgroundColor:
            primary && !disabled ? core.phosphor : glass.tint(depth.well.alpha),
          borderColor: primary ? core.phosphor : glass.hairline(),
          opacity: disabled ? (primary ? 0.55 : 0.4) : 1,
        },
        style,
      ]}>
      <Mono
        size="label"
        weight="medium"
        color={primary && !disabled ? core.case : primary ? core.phosphor : core.screen}
        numberOfLines={1}>
        {label}
      </Mono>
    </Press>
  );
}

/**
 * A flat text action - no box, no fill.
 *
 * The screens had grown three private copies of this: "remove", "+ photo",
 * "+ more options", each a Pressable wrapping a Mono with its own padding, and
 * each a different size. One of them was 20 px tall. This one is `metric.tap`
 * like every other control, which is the whole reason it is here rather than
 * inline.
 */
export function Quiet({
  label,
  onPress,
  disabled = false,
  color = core.dim,
  style,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  color?: string;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      hitSlop={space.snug}
      style={({ pressed }) => [
        styles.quiet,
        { opacity: disabled ? 0.4 : pressed ? 0.7 : 1 },
        style,
      ]}>
      <Mono size="label" weight="medium" color={color} numberOfLines={1}>
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
 * One chip in a wrapping row of them - a material, an operation, a filter.
 *
 * Three screens had drawn their own and they had drifted: two heights, two
 * border colours, and one that changed its border to phosphor for "selected"
 * while another changed it for "already used". The state is named here.
 */
export function Chip({
  label,
  active = false,
  onPress,
  disabled = false,
}: {
  label: string;
  active?: boolean;
  onPress: () => void;
  disabled?: boolean;
}) {
  // A TAP THAT ANSWERS BEFORE THE ENGINE DOES. A build takes minutes on this
  // machine and a filter takes a round trip; the gap between a finger landing
  // and anything changing is where somebody taps again. The scale is local
  // and instant because it involves no request. See src/motion.tsx.
  return (
    <Press
      onPress={onPress}
      disabled={disabled}
      style={[
        styles.chip,
        active && styles.chipOn,
        { opacity: disabled ? 0.4 : 1 },
      ]}>
      <Mono size="label" weight={active ? 'medium' : 'regular'}
        color={active ? core.phosphor : core.dim}>
        {label}
      </Mono>
    </Press>
  );
}

/**
 * A labelled text field, with its own explanation under it.
 *
 * WHY THE LABEL IS ALWAYS VISIBLE rather than a placeholder that vanishes:
 * the one field in this app somebody types into cold is the machine's
 * address, and a field whose label disappeared the moment they started typing
 * is a field they have to clear to find out what it was.
 */
export function Field({
  label,
  value,
  onChangeText,
  placeholder,
  note,
  keyboardType,
  autoCapitalize = 'none',
  onSubmitEditing,
}: {
  label: string;
  value: string;
  onChangeText: (next: string) => void;
  placeholder?: string;
  note?: string;
  keyboardType?: KeyboardTypeOptions;
  autoCapitalize?: 'none' | 'sentences' | 'words' | 'characters';
  onSubmitEditing?: () => void;
}) {
  return (
    <View style={styles.field}>
      <Mono size="micro" color={core.dim}>
        {label}
      </Mono>
      <Surface step="well" style={styles.fieldWell}>
        <TextInput
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={core.dim}
          keyboardType={keyboardType}
          autoCapitalize={autoCapitalize}
          autoCorrect={false}
          onSubmitEditing={onSubmitEditing}
          returnKeyType="done"
          style={styles.fieldInput}
        />
      </Surface>
      {note ? (
        <Prose size="body" color={core.dim}>
          {note}
        </Prose>
      ) : null}
    </View>
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
      <Mono size="label" color={core.dim} style={styles.rowLabel}>
        {label}
      </Mono>
      <Mono size="label" weight="medium" color={valueColor} style={styles.rowValue}>
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
  state: 'pass' | 'warn' | 'fail' | 'waiting' | 'info';
  text: string;
  style?: StyleProp<ViewStyle>;
}) {
  const marks = { pass: 'OK', warn: '!', fail: 'X', waiting: '...', info: 'i' } as const;
  const colours = {
    pass: pen.pass,
    warn: pen.warn,
    fail: pen.fail,
    waiting: core.dim,
    info: core.dim,
  } as const;

  return (
    <View style={[styles.verdict, style]}>
      <View style={[styles.mark, { borderColor: colours[state] }]}>
        <Mono size="micro" weight="bold" color={colours[state]}>
          {marks[state]}
        </Mono>
      </View>
      <Mono size="label" color={colours[state]} style={styles.verdictText} numberOfLines={3}>
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

/**
 * Nothing here yet, and what to do about it.
 *
 * An empty list used to be one grey sentence, which reads as a screen that
 * failed to load. An empty state has to say what would fill it.
 */
export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <View style={styles.empty}>
      <Mono size="label" color={core.dim}>
        {title}
      </Mono>
      {hint ? (
        <Prose size="body" color={core.dim} style={styles.emptyHint}>
          {hint}
        </Prose>
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// the header, on every screen that is not the root of a tab
// ---------------------------------------------------------------------------

/**
 * The top of a screen: a way back, a title, a subtitle, and room on the right.
 *
 * Every screen had grown its own, and they had drifted - "‹ start" on one and
 * "‹ library" on another, both of which went to the same place, and one of
 * them lied about where. A back arrow with no word is not an improvement; the
 * word is what makes it a promise.
 */
export function Header({
  back,
  backLabel = 'back',
  title,
  subtitle,
  right,
}: {
  back?: () => void;
  backLabel?: string;
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}) {
  return (
    <View style={styles.header}>
      {back ? <Quiet label={`‹ ${backLabel}`} onPress={back} style={styles.headerBack} /> : null}
      <View style={styles.headerText}>
        <Mono size="figure" weight="medium" numberOfLines={1}>
          {title}
        </Mono>
        {subtitle ? (
          <Mono size="micro" color={core.dim} numberOfLines={1}>
            {subtitle}
          </Mono>
        ) : null}
      </View>
      {right}
    </View>
  );
}

// ---------------------------------------------------------------------------
// the tab bar
// ---------------------------------------------------------------------------

/**
 * The three places to be, always reachable.
 *
 * MESHY'S LEFT RAIL, TURNED NINETY DEGREES. Their workspace keeps every mode
 * one click away down the left edge - assets, agent, image, model, print - and
 * never buries one behind another. A phone has no left edge to spare, so the
 * same idea is a bottom bar, and the three are the three things this engine
 * actually does rather than a copy of their five.
 *
 * WHY THIS REPLACED A SEGMENTED CONTROL. The old app had "describe / open a
 * file / library" as three segments INSIDE one screen, so the library was a
 * tab of the making screen and the machine had no home at all. A tab that only
 * exists while you are on one screen is not navigation, and the proof was that
 * there was nowhere to put a setting.
 *
 * ICONS ARE DRAWN, NOT SHIPPED. No icon font is installed and adding one for
 * three glyphs would put a third font in the app. These are three paths in the
 * renderer that is already here for the rig.
 */
export type TabName = 'make' | 'library' | 'machine' | 'you';

/**
 * What each tab is called on screen, where that differs from its key.
 *
 * `machine` became `print`: the tab answers "can I print this, will it fit,
 * how long, how much filament" and shows the connection underneath. The key
 * stays, because it is the route every caller navigates by.
 */
const TAB_WORDS: Partial<Record<TabName, string>> = { machine: 'print' };

export function TabBar({
  value,
  onChange,
  badge,
}: {
  value: TabName;
  onChange: (next: TabName) => void;
  /** A count over a tab - jobs the machine is running. Zero draws nothing. */
  badge?: Partial<Record<TabName, number>>;
}) {
  const tabs: TabName[] = ['make', 'library', 'machine', 'you'];
  return (
    <Surface step="float" style={styles.tabBar}>
      {tabs.map((name) => {
        const active = name === value;
        const count = badge?.[name] ?? 0;
        return (
          <Pressable
            key={name}
            onPress={() => onChange(name)}
            style={({ pressed }) => [styles.tab, { opacity: pressed ? 0.7 : 1 }]}>
            <View>
              <TabGlyph name={name} colour={active ? core.phosphor : core.dim} />
              {count > 0 ? (
                <View style={styles.badge}>
                  <Mono size="micro" weight="bold" color={core.case}>
                    {count > 9 ? '9+' : String(count)}
                  </Mono>
                </View>
              ) : null}
            </View>
            {/* THE WORD UNDER EVERY ICON, ALWAYS. Three drawn glyphs are three
                guesses without it, and brief 6.7's ban on colour-only status
                is the same argument: the label is what carries the meaning and
                the colour only says which one is current. */}
            <Mono size="micro" weight={active ? 'medium' : 'regular'}
              color={active ? core.phosphor : core.dim}>
              {/* THE WORD, NOT THE KEY. The tab is called `machine` in the
                  code because that is what it routes to and renaming the
                  route would touch every caller - but the question somebody
                  opens it with is "can I print this", not "how is the
                  machine". The connection lives on it either way. */}
              {TAB_WORDS[name] ?? name}
            </Mono>
          </Pressable>
        );
      })}
    </Surface>
  );
}

/** One tab glyph at 22 px, in the drafting language the rest of the app uses. */
function TabGlyph({ name, colour }: { name: TabName; colour: string }) {
  const s = 22;
  if (name === 'make') {
    // A plus: the only universally read "new", and legible at 22 px where
    // anything with an interior would close up.
    return (
      <Svg width={s} height={s} viewBox="0 0 22 22">
        <Path d="M11 4 V18 M4 11 H18" stroke={colour} strokeWidth={2}
          strokeLinecap="round" fill="none" />
      </Svg>
    );
  }
  if (name === 'library') {
    // Four panes: the same two-across grid the library itself draws, which is
    // the only icon here that is a picture of its own screen.
    return (
      <Svg width={s} height={s} viewBox="0 0 22 22">
        {[
          [4, 4],
          [12.5, 4],
          [4, 12.5],
          [12.5, 12.5],
        ].map(([x, y], i) => (
          <Rect key={i} x={x} y={y} width={5.5} height={5.5} rx={1}
            stroke={colour} strokeWidth={1.6} fill="none" />
        ))}
      </Svg>
    );
  }
  if (name === 'machine') {
    // A nozzle over a bed: the machine, in two strokes. A gear would say
    // "settings" and this tab is not preferences - it is what the engine is
    // doing right now, and the profile it is doing it against.
    return (
      <Svg width={s} height={s} viewBox="0 0 22 22">
        <Path d="M7.5 3 H14.5 L13 10 H9 Z" stroke={colour} strokeWidth={1.6}
          strokeLinejoin="round" fill="none" />
        <Path d="M11 12 V14" stroke={colour} strokeWidth={1.6} strokeLinecap="round" />
        <Path d="M3.5 18 H18.5" stroke={colour} strokeWidth={2} strokeLinecap="round" />
      </Svg>
    );
  }
  // A head and shoulders: you. The plainest possible glyph, because this tab
  // is about a person rather than a thing - and because the alternative, a
  // gear, is the one this set already declined to use for the machine.
  return (
    <Svg width={s} height={s} viewBox="0 0 22 22">
      <Path d="M11 4 m -3.2 0 a 3.2 3.2 0 1 0 6.4 0 a 3.2 3.2 0 1 0 -6.4 0"
        stroke={colour} strokeWidth={1.6} fill="none" />
      <Path d="M4.5 18 a 6.5 6.5 0 0 1 13 0" stroke={colour} strokeWidth={1.6}
        strokeLinecap="round" fill="none" />
    </Svg>
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
  quiet: {
    minHeight: metric.tap,
    justifyContent: 'center',
    paddingHorizontal: space.snug,
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
  chip: {
    minHeight: metric.tap - space.base,
    justifyContent: 'center',
    paddingHorizontal: space.base,
    borderRadius: radius.control,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: core.etch,
  },
  chipOn: {
    borderColor: core.phosphor,
  },
  field: {
    gap: space.tight,
  },
  fieldWell: {
    paddingHorizontal: space.snug,
  },
  fieldInput: {
    minHeight: metric.tap,
    color: core.screen,
    fontFamily: type.mono,
    fontSize: type.size.body,
    padding: 0,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingVertical: space.tight,
    gap: space.base,
  },
  rowLabel: {
    flexShrink: 0,
  },
  // A LONG VALUE WRAPS RATHER THAN PUSHING THE LABEL OFF. "printer" against a
  // name from the machine's own config is not a number, and the old Row let it
  // shove the label out of the screen.
  rowValue: {
    flex: 1,
    textAlign: 'right',
  },
  verdict: {
    flexDirection: 'row',
    alignItems: 'flex-start',
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
  empty: {
    paddingVertical: space.loose,
    gap: space.snug,
  },
  emptyHint: {
    maxWidth: 420,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
    paddingVertical: space.tight,
  },
  headerBack: {
    paddingLeft: 0,
  },
  headerText: {
    flex: 1,
  },
  tabBar: {
    flexDirection: 'row',
    paddingVertical: space.snug,
  },
  tab: {
    flex: 1,
    alignItems: 'center',
    gap: space.hair,
    minHeight: metric.tap,
    justifyContent: 'center',
  },
  badge: {
    position: 'absolute',
    right: -6,
    top: -3,
    minWidth: 15,
    height: 15,
    paddingHorizontal: 3,
    borderRadius: radius.edge,
    backgroundColor: core.phosphor,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
