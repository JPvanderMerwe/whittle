/**
 * Movement, in the small amounts this app has any business using.
 *
 * WHAT MOTION IS FOR HERE. Every screen in whittle is showing somebody a fact
 * about a physical object - a size, a verdict, whether a part fits a bed. The
 * job of an animation is to say where a thing came from and that a tap
 * landed, and then get out of the way. Anything that makes a person wait to
 * read a number is working against the product.
 *
 * SO THE RULES ARE SHORT:
 *
 *   * nothing moves for longer than a fifth of a second
 *   * nothing moves more than a few pixels
 *   * a value never animates - the number is the point, and a figure that
 *     counts up is a figure you cannot read yet
 *   * everything runs on the native driver, so a slow engine call cannot
 *     make the interface stutter
 *
 * NO NEW DEPENDENCY. React Native's own Animated does all of this with the
 * native driver. Reanimated is a better library and it is a large native
 * module to add for a fade and a scale - see how quickly `expo-blur` earned
 * its place by comparison: it does something that cannot be faked.
 *
 * REDUCED MOTION IS HONOURED. Somebody who has asked their phone to stop
 * animating things has asked this app too, and the whole point of these being
 * small is that skipping them changes nothing about what is on screen.
 */

import React, { useEffect, useRef, useState } from 'react';
import {
  AccessibilityInfo,
  Animated,
  Easing,
  Pressable,
  StyleSheet,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

/** How long anything here may take. See the rules above. */
const QUICK = 180;
/** How far a thing may travel on its way in. */
const RISE = 10;

/**
 * Whether the person has asked for less movement.
 *
 * Read once and watched, because it can change while the app is open.
 * Defaults to "animate" when the query fails - a platform that cannot answer
 * is not a platform that has said no.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    let live = true;
    AccessibilityInfo.isReduceMotionEnabled?.()
      .then((on) => live && setReduced(Boolean(on)))
      .catch(() => undefined);
    const watch = AccessibilityInfo.addEventListener?.(
      'reduceMotionChanged',
      (on) => live && setReduced(Boolean(on)),
    );
    return () => {
      live = false;
      watch?.remove?.();
    };
  }, []);

  return reduced;
}

/**
 * Something arriving: a short fade with a few pixels of rise.
 *
 * WHY IT RISES RATHER THAN SCALES. A panel that grows from 95% reads as
 * "appearing from nowhere"; one that comes up from below reads as "there is
 * more of this, and it is in that direction", which on a scrolling screen is
 * true. It is also the direction the content actually flows.
 *
 * `delay` staggers a list. Small values only: three panels at 40 ms apart is
 * a screen assembling itself, and ten at 100 ms is a screen keeping you
 * waiting.
 */
export function Appear({
  delay = 0,
  style,
  children,
}: {
  delay?: number;
  style?: StyleProp<ViewStyle>;
  children?: React.ReactNode;
}) {
  const reduced = useReducedMotion();
  const progress = useRef(new Animated.Value(reduced ? 1 : 0)).current;

  useEffect(() => {
    if (reduced) {
      progress.setValue(1);
      return undefined;
    }
    const run = Animated.timing(progress, {
      toValue: 1,
      duration: QUICK,
      delay,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    });
    run.start();
    return () => run.stop();
  }, [delay, progress, reduced]);

  return (
    <Animated.View
      style={[
        style,
        {
          opacity: progress,
          transform: [
            {
              translateY: progress.interpolate({
                inputRange: [0, 1],
                outputRange: [RISE, 0],
              }),
            },
          ],
        },
      ]}>
      {children}
    </Animated.View>
  );
}

/**
 * A tap that answers immediately, whatever the engine is doing.
 *
 * THE ONE PIECE OF MOTION THIS APP GENUINELY NEEDS. A build takes minutes on
 * this machine, and the gap between a finger landing and anything changing is
 * where somebody taps again - which is how two builds get started. The press
 * state is local and instant: it cannot be delayed by a request, because it
 * does not involve one.
 *
 * SCALE AND NOT COLOUR, because every colour in this theme carries meaning -
 * amber is the accent, green is a pass, red is a failure - and borrowing one
 * for a transient state makes those meanings softer.
 */
export function Press({
  onPress,
  disabled = false,
  style,
  children,
}: {
  onPress: () => void;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  children?: React.ReactNode;
}) {
  const reduced = useReducedMotion();
  const scale = useRef(new Animated.Value(1)).current;

  const to = (value: number) => {
    if (reduced) return;
    Animated.spring(scale, {
      toValue: value,
      useNativeDriver: true,
      speed: 40,
      bounciness: 0,
    }).start();
  };

  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      onPressIn={() => to(0.97)}
      onPressOut={() => to(1)}
      style={style}>
      <Animated.View style={{ transform: [{ scale }] }}>{children}</Animated.View>
    </Pressable>
  );
}

/**
 * A slow sweep across something that is not ready yet.
 *
 * FOR A SHAPE THAT IS COMING, NOT FOR A SPINNER. A thumbnail that has been
 * asked for and is being rendered is a known shape with unknown content, and
 * the honest thing to draw is that shape, quietly busy. A spinner in the same
 * place says "something is happening somewhere", which is less.
 *
 * DELIBERATELY SLOW - a second and a half. A fast shimmer reads as urgency,
 * and nothing here is urgent: the server is rendering a part, which takes as
 * long as it takes.
 */
export function Shimmer({
  style,
  children,
}: {
  style?: StyleProp<ViewStyle>;
  children?: React.ReactNode;
}) {
  const reduced = useReducedMotion();
  const wave = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (reduced) return undefined;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(wave, {
          toValue: 1,
          duration: 1500,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true,
        }),
        Animated.timing(wave, {
          toValue: 0,
          duration: 1500,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [reduced, wave]);

  return (
    <Animated.View
      style={[
        style,
        { opacity: reduced ? 0.6 : wave.interpolate({ inputRange: [0, 1], outputRange: [0.35, 0.75] }) },
      ]}>
      {children}
    </Animated.View>
  );
}

export const motionStyles = StyleSheet.create({
  fill: { flex: 1 },
});
