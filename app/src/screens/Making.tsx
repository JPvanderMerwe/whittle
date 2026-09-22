/**
 * Watching a part get built.
 *
 * A generate takes minutes: the model is asked, a spec is filled and
 * validated, geometry is built, every check is run, and options are walked off
 * the spec's own axes. The one thing this screen must never do is show a
 * spinner and a guess at how long is left.
 *
 * SO IT SHOWS WHAT THE ENGINE ACTUALLY SAID. Every line here is a `note` the
 * server emitted from inside the build - "no template fits - composing from
 * primitives", "verify: passed", "dropped taller - wall below two extrusions".
 * That is the difference between waiting and watching, and it is also the only
 * honest progress indicator: nobody knows how many attempts a request needs
 * until it has had them.
 *
 * POLLED, NOT STREAMED - see Api.job. The route returns the whole event list
 * every time, so a poll that misses a beat, or a phone that locked its screen
 * for a minute, loses nothing.
 *
 * "STOP WATCHING" MEANT NOTHING BEFORE, and that was the fault worth fixing
 * here. The button left the screen and the build carried on, which is correct
 * and is the whole point of running on the machine - but nothing anywhere in
 * the app then showed the build, so leaving felt like abandoning it. The
 * library now carries a live strip of everything running, so this screen says
 * where the build goes when you leave it, by name.
 *
 * NOT EVERY JOB IS A LONG ONE, AND THIS SCREEN USED TO INSIST THEY WERE.
 * Setting a number rebuilds a part from its spec with no model involved -
 * measured at six seconds - and it arrived here to be told "leave the screen,
 * lock the phone, and it carries on under the library tab". Advice about
 * walking away, for something that finishes before you could. Worse, it made
 * the two kinds of work look equally expensive, so a slider felt as costly as
 * a generate and people would hesitate over it.
 *
 * The caller knows which it started, so it says so. Nothing here guesses from
 * elapsed time: a generate that happens to be quick is still a generate, and a
 * rebuild that is slow because the mesh is enormous is still a rebuild.
 */

import React, { useEffect, useRef, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import type { Api, BuiltPart, JobEvent } from '../api';
import { core, pen, space } from '../tokens';
import { Waiting } from '../Rig';
import { Button, Header, Mono, Panel, Problem, Prose, Verdict } from '../ui';

/** How often to ask. Slow enough to be nothing on the wire, fast enough to read. */
const EVERY_MS = 1000;

/**
 * What kind of work this is, which decides what the screen promises.
 *
 *   generate  words in, a part out. The model is asked, a spec is filled and
 *             validated, geometry is built, every check is run - minutes.
 *   refine    a sentence against an existing part. The parser decides the
 *             common case in a second; anything it cannot decide goes to the
 *             model, so it is a generate again.
 *   params    numbers set directly. No model, no parser - load the spec, apply
 *             the values, rebuild. Seconds.
 */
export type JobKind = 'generate' | 'refine' | 'params';

interface Props {
  api: Api;
  jobId: string;
  request: string;
  kind: JobKind;
  onBuilt: (part: BuiltPart) => void;
  onGiveUp: () => void;
}

export function MakingScreen({ api, jobId, request, kind, onBuilt, onGiveUp }: Props) {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [failure, setFailure] = useState<string | null>(null);
  const [started] = useState(() => Date.now());
  const [now, setNow] = useState(Date.now());
  const log = useRef<ScrollView | null>(null);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      if (!live) return;
      try {
        const state = await api.job(jobId);
        if (!live) return;
        setEvents(state.events);
        setNow(Date.now());

        if (state.done) {
          const result = state.result as BuiltPart | { ok: false; message: string } | null;
          if (result && (result as BuiltPart).ok) {
            onBuilt(result as BuiltPart);
          } else {
            // A BUILD THAT FAILED IS NOT AN ERROR IN THE APP. The engine tried
            // and could not produce something that passes verification, and it
            // says why - which is worth reading rather than replacing with
            // "something went wrong".
            setFailure(
              (result as { message?: string })?.message ??
                'the machine finished without producing a part',
            );
          }
          return;
        }
      } catch (error: any) {
        // A DROPPED POLL IS NOT A DROPPED BUILD. The job runs on the server's
        // own thread; losing the connection for a moment means asking again,
        // not abandoning three minutes of work.
        if (!live) return;
      }
      timer = setTimeout(poll, EVERY_MS);
    };

    poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [api, jobId, onBuilt]);

  const lines = events.filter((event) => typeof event.text === 'string');
  const elapsed = Math.round((now - started) / 1000);
  // A rebuild with no model in it. See JobKind.
  const quick = kind === 'params';

  return (
    <View style={styles.screen}>
      <Header
        back={onGiveUp}
        backLabel={quick ? 'back' : 'leave it running'}
        title={failure ? 'it did not build' : quick ? 'rebuilding it' : 'making it'}
        subtitle={failure ? undefined : `${elapsed}s`}
      />

      <Panel>
        <Mono size="micro" color={core.dim}>
          {quick ? 'what changed' : 'what you asked for'}
        </Mono>
        <Prose size="reading" color={core.screen}>
          {request}
        </Prose>
      </Panel>

      {failure ? (
        <Problem text={failure} actionLabel="back" onAction={onGiveUp} />
      ) : (
        <View style={styles.working}>
          {/* THE CLOCK, NOT A PERCENTAGE. Nobody knows how many attempts a
              request needs until it has had them, and a progress bar that is
              invented is a lie told once a second. So the rig turns, the
              elapsed time counts up, and the log below says what is actually
              happening. */}
          <Waiting caption={`${elapsed}s · ${lastWord(lines)}`} />
        </View>
      )}

      <Panel title="what the machine is doing" style={styles.logPanel}>
        <ScrollView
          ref={log}
          onContentSizeChange={() => log.current?.scrollToEnd({ animated: true })}>
          {lines.length === 0 ? (
            <Prose size="body" color={core.dim}>
              waiting for the first word back…
            </Prose>
          ) : (
            lines.map((event, index) => (
              <View key={index} style={styles.line}>
                <Mono size="micro" color={core.dim}>
                  {String(index + 1).padStart(2, '0')}
                </Mono>
                <Mono
                  size="label"
                  color={verdictColour(event.text!)}
                  style={styles.lineText}>
                  {event.text}
                </Mono>
              </View>
            ))
          )}
        </ScrollView>
      </Panel>

      {!failure ? (
        quick ? (
          // NO ADVICE ABOUT WALKING AWAY from something that finishes before
          // you could. What is worth saying about a rebuild is the thing that
          // makes it safe to keep doing: it writes a new part, so the one you
          // changed is still there.
          <Verdict
            state="waiting"
            text="rebuilding from the spec - no model involved, so this is seconds. The part you changed is kept."
          />
        ) : (
          <>
            {/* WHERE IT GOES IF YOU LEAVE, BY NAME. "the screen can lock" was
                true and unhelpful: it said the build survives without saying
                where to find it again, so leaving the screen was a gamble. */}
            <Verdict
              state="waiting"
              text="this runs on the machine, not the phone - leave the screen, lock the phone, and it carries on under the library tab"
            />
            <Button label="leave it running" onPress={onGiveUp} />
          </>
        )
      ) : null}
    </View>
  );
}

/** The most recent thing the machine said, for the rig's caption. */
function lastWord(lines: JobEvent[]): string {
  const latest = lines[lines.length - 1]?.text;
  return latest ? latest.slice(0, 42) : 'asking the machine';
}

/**
 * The pen for one line of the log.
 *
 * Only the lines that carry a verdict get a colour, and each still says its
 * state in words - brief 6.7 forbids colour-only status. Everything else is
 * plain, so the two that matter stand out of thirty that do not.
 */
function verdictColour(text: string): string {
  const lower = text.toLowerCase();
  if (lower.startsWith('verify:')) {
    if (lower.includes('pass')) return pen.pass;
    if (lower.includes('fail')) return pen.fail;
    return pen.warn;
  }
  if (lower.startsWith('dropped') || lower.startsWith('could not')) return pen.warn;
  return core.screen;
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    padding: space.base,
    gap: space.base,
  },
  working: {
    alignItems: 'center',
  },
  logPanel: {
    flex: 1,
  },
  line: {
    flexDirection: 'row',
    gap: space.snug,
    paddingVertical: space.hair,
  },
  lineText: {
    flex: 1,
  },
});
