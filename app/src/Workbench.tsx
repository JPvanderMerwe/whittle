/**
 * The workbench: one surface for every object, whatever it came from.
 *
 * WHAT THIS REPLACED, AND WHY IT IS A FRAME RATHER THAN A SCREEN
 * --------------------------------------------------------------
 * There were two screens doing the same job with different words:
 *
 *   Part.tsx    change it | checks | measured | report     a built part
 *   Edit.tsx    change it | model | checks | save          an imported mesh
 *
 * The contents genuinely differ - a design has a spec and named dimensions, a
 * mesh has a stack of operations - so merging them into one component would be
 * one component with two halves and an `if` down the middle. What has no
 * business differing is the FRAME: where the object sits, where the verdict
 * is, where the box you type in is, and what the four panels are called. So
 * the frame is this, and each screen fills it.
 *
 * THE SHAPE, TOP TO BOTTOM
 * ------------------------
 *   header      what it is, and the way back
 *   the object  everything that is left, because it is the point
 *   standing    one line: does it print. Never a tab. See workbench.ts.
 *   drawer      four words; one opens, the rest stay shut
 *   say         the box, pinned, always there
 *
 * At rest that is three things on screen: the object, whether it prints, and
 * somewhere to say the next thing. Everything else is one tap and takes half
 * the screen when it is open, so the object never leaves.
 *
 * THE BOX IS THE POINT, AND IT IS WHY IT IS PINNED
 * ------------------------------------------------
 * The other tools in this space hand you a finished mesh: prompt, four
 * candidates, pick one, download. The object arrives done. whittle's object
 * arrives as STOCK - the whole idea in the name is that you keep working it
 * until it is the thing you meant - so the control that takes the next cut is
 * the one that must never be behind a tab. It was behind one on a part, and on
 * an import it did not exist at all.
 *
 * WHY THE DRAWER SLIDES OVER AND DOES NOT PUSH
 * --------------------------------------------
 * Pushing the viewport up resizes the GL surface, and every resize of an
 * expo-gl context is a reallocation of its buffers mid-gesture. Overlaying
 * leaves the renderer alone: it keeps its size, the drawer is drawn on top of
 * the lower half of it, and the object above stays exactly where the eye left
 * it.
 */

import React, { useEffect, useRef } from 'react';
import {
  Animated,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { QUICK, useReducedMotion } from './motion';
import { core, metric, pen, radius, space, type } from './tokens';
import { Button, Header, Mono, Surface } from './ui';
import { PANELS, type PanelName, type Standing, type Tone } from './workbench';

/** What the standing line's tone maps to in the pen. */
const TONE_COLOUR: Record<Tone, string> = {
  pass: pen.pass,
  warn: pen.warn,
  fail: pen.fail,
  unknown: core.dim,
};

/** The mark beside it, so the state survives somebody who cannot see colour. */
const TONE_MARK: Record<Tone, string> = {
  pass: 'OK',
  warn: '!',
  fail: 'X',
  unknown: '?',
};

export interface SayBox {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  hint: string;
  busy: boolean;
  /** The word on the button. "change it" on a design, "do it" on a mesh. */
  action: string;
}

interface Props {
  title: string;
  subtitle?: string;
  onClose: () => void;
  /** Anything the header wants on its right - a layout switch, a menu. */
  headerRight?: React.ReactNode;

  standing: Standing;
  /** One line of history, when there is any. Tapping it opens the chain. */
  chain?: { label: string; onPress: () => void } | null;

  /** Which panel is open, or none. Owned by the screen so it survives a rebuild. */
  panel: PanelName | null;
  onPanel: (panel: PanelName | null) => void;
  /** The four panels. A screen with nothing for one passes null and it greys. */
  panels: Partial<Record<PanelName, React.ReactNode>>;

  say: SayBox | null;
  /** Anything that must sit above the box - unbuilt changes, a question. */
  above?: React.ReactNode;

  /** The object. */
  children?: React.ReactNode;
}

export function Workbench({
  title,
  subtitle,
  onClose,
  headerRight,
  standing,
  chain,
  panel,
  onPanel,
  panels,
  say,
  above,
  children,
}: Props) {
  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Header back={onClose} title={title} subtitle={subtitle} right={headerRight} />

      {/* THE OBJECT TAKES WHAT IS LEFT. Not a fixed height: on a tall phone
          that would leave a band of nothing under it, and on a short one it
          would push the box off the bottom. */}
      <View style={styles.stage}>
        {children}
        {panel ? <Drawer onClose={() => onPanel(null)}>{panels[panel]}</Drawer> : null}
      </View>

      <StandingLine standing={standing} />

      {chain ? (
        <Pressable onPress={chain.onPress} style={styles.chain}>
          <Mono size="micro" color={core.dim} numberOfLines={1}>
            {chain.label}
          </Mono>
          <Mono size="micro" color={core.dim}>
            ›
          </Mono>
        </Pressable>
      ) : null}

      <View style={styles.drawerBar}>
        {PANELS.map((name) => {
          const has = Boolean(panels[name]);
          const open = panel === name;
          return (
            <Pressable
              key={name}
              disabled={!has}
              onPress={() => onPanel(open ? null : name)}
              style={[styles.drawerTab, open ? styles.drawerTabOpen : null]}
            >
              <Mono
                size="label"
                weight={open ? 'medium' : 'regular'}
                color={!has ? core.dim : open ? core.screen : core.phosphor}
              >
                {name}
              </Mono>
            </Pressable>
          );
        })}
      </View>

      {above}

      {say ? (
        <Surface step="pill" style={styles.say}>
          <TextInput
            value={say.value}
            onChangeText={say.onChange}
            onSubmitEditing={say.onSend}
            returnKeyType="send"
            placeholder={say.hint}
            placeholderTextColor={core.dim}
            style={styles.input}
          />
          <Button
            label={say.action}
            primary
            onPress={say.onSend}
            disabled={!say.value.trim() || say.busy}
          />
        </Surface>
      ) : null}
    </KeyboardAvoidingView>
  );
}

/**
 * Does it print. One line, always on screen.
 *
 * THE PROMISE THE PRODUCT MAKES, WHERE IT CAN BE SEEN. It was a tab on both
 * screens, which means it was checked once and then never again - and "always
 * printable" is not something you check once. The headline is short enough to
 * read without stopping; the detail is the engine's own first sentence about
 * what is wrong, truncated rather than summarised, because a summary written
 * here would be this screen's opinion of a measurement it did not take.
 */
function StandingLine({ standing }: { standing: Standing }) {
  const colour = TONE_COLOUR[standing.tone];
  return (
    <View style={[styles.standing, { borderTopColor: colour }]}>
      <View style={[styles.mark, { borderColor: colour }]}>
        <Mono size="micro" weight="bold" color={colour}>
          {TONE_MARK[standing.tone]}
        </Mono>
      </View>
      <View style={styles.standingText}>
        <Mono size="label" weight="medium" color={colour} numberOfLines={1}>
          {standing.headline}
        </Mono>
        {standing.detail ? (
          <Mono size="micro" color={core.dim} numberOfLines={1}>
            {standing.detail}
          </Mono>
        ) : null}
      </View>
    </View>
  );
}

/**
 * The open panel, over the lower half of the object.
 *
 * IT SLIDES AND IT DOES NOT PUSH - see the note at the top of this file about
 * expo-gl and mid-gesture reallocation. Reduced motion gets the same panel with
 * no travel rather than no panel.
 */
function Drawer({ children, onClose }: { children?: React.ReactNode; onClose: () => void }) {
  const still = useReducedMotion();
  const slide = useRef(new Animated.Value(still ? 1 : 0)).current;

  useEffect(() => {
    if (still) {
      slide.setValue(1);
      return;
    }
    Animated.timing(slide, {
      toValue: 1,
      duration: QUICK,
      useNativeDriver: true,
    }).start();
  }, [slide, still]);

  return (
    <Animated.View
      style={[
        styles.drawer,
        {
          opacity: slide,
          transform: [
            { translateY: slide.interpolate({ inputRange: [0, 1], outputRange: [24, 0] }) },
          ],
        },
      ]}
    >
      <Surface step="panel" style={styles.drawerSheet}>
        <Pressable onPress={onClose} style={styles.grip} hitSlop={12}>
          <View style={styles.gripBar} />
        </Pressable>
        <ScrollView
          style={styles.drawerScroll}
          contentContainerStyle={styles.drawerContent}
          keyboardShouldPersistTaps="handled"
        >
          {children}
        </ScrollView>
      </Surface>
    </Animated.View>
  );
}

/** Nothing for this panel, said rather than left blank. */
export function NothingHere({ what, hint }: { what: string; hint?: string }) {
  return (
    <View style={styles.nothing}>
      <Mono size="label" color={core.dim}>
        {what}
      </Mono>
      {hint ? (
        <Mono size="micro" color={core.dim} style={styles.nothingHint}>
          {hint}
        </Mono>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  stage: { flex: 1, justifyContent: 'flex-end' },

  standing: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
    paddingHorizontal: space.wide,
    paddingVertical: space.snug,
    borderTopWidth: 2,
  },
  standingText: { flex: 1 },
  mark: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },

  chain: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: space.wide,
    paddingBottom: space.snug,
  },

  drawerBar: {
    flexDirection: 'row',
    paddingHorizontal: space.wide,
    gap: space.snug,
  },
  drawerTab: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: space.snug,
    borderRadius: radius.control,
  },
  drawerTabOpen: { backgroundColor: core.phosphor },

  drawer: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    // HALF THE STAGE, so the object is still there while the numbers move. A
    // drawer that covered it would make every slider a guess - and now that a
    // slider redraws the shape as it moves, that is the whole point of the
    // screen rather than a nicety. Measured on the phone at 58% the object was
    // a sliver; half leaves enough of it to judge a change by.
    maxHeight: '50%',
  },
  // FLEXSHRINK, NOT FLEX. The sheet's parent is positioned by its edges with
  // no height of its own, so its height comes from content and is then capped
  // by maxHeight. A ScrollView with flex:1 inside a content-sized parent
  // collapses to nothing; one with no flex at all sizes to its content, is
  // clipped by the cap, and never scrolls because it does not know it was
  // clipped. Shrinking is the one that grows to content, stops at the cap and
  // scrolls the rest.
  drawerSheet: { flexShrink: 1, borderBottomLeftRadius: 0, borderBottomRightRadius: 0 },
  drawerScroll: { flexShrink: 1 },
  drawerContent: { padding: space.wide, gap: space.snug, paddingBottom: space.loose },
  grip: { alignItems: 'center', paddingVertical: space.snug },
  gripBar: { width: 36, height: 3, borderRadius: 2, backgroundColor: core.dim },

  say: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
    marginHorizontal: space.wide,
    marginTop: space.snug,
    marginBottom: space.wide,
    paddingLeft: space.base,
    paddingRight: space.snug,
  },
  input: {
    flex: 1,
    minHeight: metric.tap,
    color: core.screen,
    fontFamily: type.mono,
    fontSize: type.size.label,
    paddingVertical: space.snug,
  },

  nothing: { paddingVertical: space.loose, alignItems: 'center', gap: space.tight },
  nothingHint: { textAlign: 'center' },
});
