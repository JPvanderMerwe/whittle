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
 */

import React, { useEffect, useRef, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import type { Api, BuiltPart, JobEvent } from '../api';
import { core, pen, space } from '../tokens';
import { Waiting } from '../Rig';
import { Button, Mono, Panel, Problem, Prose, Verdict } from '../ui';

/** How often to ask. Slow enough to be nothing on the wire, fast enough to read. */
const EVERY_MS = 1000;

interface Props {
  api: Api;
  jobId: string;
  request: string;
  onBuilt: (part: BuiltPart) => void;
  onGiveUp: () => void;
}

export function MakingScreen({ api, jobId, request, onBuilt, onGiveUp }: Props) {
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

  return (
    <View style={styles.screen}>
      <View style={styles.head}>
        <Mono size="micro" color={core.dim}>
          making
        </Mono>
        <Prose size="reading" color={core.screen}>
          {request}
        </Prose>
      </View>

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
        <>
          <Verdict
            state="waiting"
            text="this runs on the machine, not the phone - the screen can lock"
          />
          <Button label="stop watching" onPress={onGiveUp} />
        </>
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
  head: {
    paddingTop: space.loose,
    gap: space.tight,
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
