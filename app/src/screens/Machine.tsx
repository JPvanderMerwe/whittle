/**
 * The machine: where it is, what it is, and what it can do.
 *
 * THE APP HAD NO SETTINGS AT ALL, and one consequence was not cosmetic: the
 * server address was a constant in api.ts, so a phone that was not plugged in
 * by USB could not be made to work. The old screen said "run `adb reverse
 * tcp:8765 tcp:8765`" and offered a retry button, which is instructions with
 * no control beside them.
 *
 * WHAT IS SETTABLE HERE, AND WHAT IS NOT
 * --------------------------------------
 * Two things are settable, because two things are the app's to decide: the
 * address of the machine, and which material to ask for. Everything else on
 * this screen is READ-ONLY, and that is the honest shape rather than a
 * limitation - the printer, the bed, the nozzle and the materials come out of
 * the machine's own config, which the engine reads and this app does not own.
 * Rule 29 is the reason a bed that is not configured says so instead of
 * drawing a default one: a wrong tolerance is worse than no tolerance, and a
 * setting screen that lets a phone invent a bed size is exactly how a wrong
 * one gets in.
 *
 * ABOUT THE ADDRESS. Loopback is the default and the right answer when the
 * phone is plugged in: `adb reverse tcp:8765 tcp:8765` forwards the phone's
 * own localhost to the laptop, so nothing is on the network. Typing a LAN
 * address is the alternative for somebody with no cable, and this screen says
 * plainly which of the two is in force, because "http://192.168.1.40:8765"
 * means the geometry is crossing a network and a person should be told that
 * rather than discover it.
 *
 * IT IS A LIVE VIEW NOW, NOT A SPEC SHEET. The owner's words: "currently its
 * not useful either design around the api and make it better or have some
 * useful use of this tab but something live and shows the engine working."
 *
 * Fair. It listed a printer, a bed and a materials array that do not change
 * from one week to the next - a page you read once and never open again. The
 * thing a person actually wants from a tab called "the machine" is whether it
 * is doing anything, and what.
 *
 * So what is running leads, with the engine's own last word on each job and
 * the clock beside it; the profile it is building against follows; and the
 * settings are at the bottom where somebody goes deliberately. Nothing new is
 * fetched for it - the job list is already polled at 2.5s for the landing
 * screen and the library, and a second reader would be a second answer to
 * what the machine is doing.
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
} from 'react-native';

import type { Api, Health, LibraryPart, MachineJob, PrintFacts } from '../api';
import { cleanBase, isLoopback, LOOPBACK } from '../address';
import { core, pen, space } from '../tokens';
import { Waiting } from '../Rig';
import {
  Button,
  Chip,
  Empty,
  Field,
  Mono,
  Panel,
  Problem,
  Prose,
  Quiet,
  Row,
  Surface,
  Verdict,
} from '../ui';

/**
 * Can I print this, and what will it cost me.
 *
 * WHAT IS MEASURED AND WHAT IS ASKED FOR. Everything above the slicer line -
 * does it fit the bed, how many layers, does it need support, how many pieces
 * - was measured when the part was built and costs nothing to show. Time and
 * filament are a slicer's answer and nothing else's: they depend on walls,
 * infill and speed, so they are fetched only when somebody asks, and if no
 * slicer is installed the panel says which one to install rather than
 * pretending.
 *
 * NO ESTIMATE IS EVER SHOWN AS A FACT. A weight computed here from solid
 * volume would be a different quantity wearing the same units - a print at
 * 15% infill uses a fraction of a solid object - and somebody loading a spool
 * would act on it.
 */
function PrintPanel({
  api,
  part,
  onPart,
}: {
  api: Api;
  part: LibraryPart;
  onPart: (dir: string) => void;
}) {
  const [facts, setFacts] = useState<PrintFacts | null>(null);
  const [slicing, setSlicing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // THE MEASURED HALF, ON OPENING. Cheap - it is read off disk - so there is
  // no reason to make somebody ask for it.
  useEffect(() => {
    let live = true;
    setFacts(null);
    setProblem(null);
    api
      .printFacts(part.dir)
      .then((found) => live && setFacts(found))
      .catch((error) => live && setProblem(String(error?.message ?? error)));
    return () => {
      live = false;
    };
  }, [api, part.dir]);

  const slice = useCallback(async () => {
    setSlicing(true);
    setProblem(null);
    try {
      setFacts(await api.printFacts(part.dir, { slice: true }));
    } catch (error: any) {
      setProblem(String(error?.message ?? error));
    } finally {
      setSlicing(false);
    }
  }, [api, part.dir]);

  const said = facts?.slicer;

  return (
    <Panel title={`printing ${part.name}`}>
      {problem ? <Problem text={problem} /> : null}

      {facts && !facts.ready ? (
        <Verdict state="warn" text={facts.why_not ?? 'nothing was built, so there is nothing to print'} />
      ) : null}

      {facts?.ready ? (
        <>
          {/* DOES IT FIT, AND BY HOW MUCH. "Too big" cannot be acted on;
              "28 mm too wide" can. */}
          {facts.fits ? (
            <Verdict
              state="pass"
              text={`fits the ${facts.printer} bed with ${facts
                .spare_mm!.map((v) => Math.round(v))
                .join(' / ')} mm to spare`}
            />
          ) : (
            <Verdict
              state="fail"
              text={`too big for the ${facts.printer}: over by ${facts
                .spare_mm!.filter((v) => v < 0)
                .map((v) => `${Math.round(-v)} mm`)
                .join(' and ')}`}
            />
          )}

          <Row label="size" value={`${facts.size_mm!.map((v) => Math.round(v)).join(' × ')} mm`} />
          <Row label="layers" value={`${facts.layers} at ${facts.layer_mm} mm`} />
          {facts.bodies && facts.bodies > 1 ? (
            <Row label="comes off as" value={`${facts.bodies} pieces`} />
          ) : null}
          {facts.volume_cm3 ? (
            <Row label="solid volume" value={`${facts.volume_cm3} cm³`} />
          ) : null}
          {facts.material ? <Row label="material" value={facts.material} /> : null}

          {facts.supports_needed ? (
            <Verdict
              state="warn"
              text={`needs support - ${Math.round(facts.unsupported_mm2 ?? 0)} mm² is unsupported`}
            />
          ) : (
            <Verdict state="pass" text="prints without support" />
          )}

          {/* WHERE THE BED SIZE CAME FROM. A part 2 mm inside a measured bed
              and 2 mm inside a published maximum are not the same news. */}
          {facts.bed_source ? (
            <Mono size="micro" color={core.dim}>
              bed: {facts.bed_source}
            </Mono>
          ) : null}

          {/* TIME AND FILAMENT: a slicer's answer or none. */}
          {said?.available === false ? (
            <Verdict state="info" text={said.why ?? 'no slicer installed'} />
          ) : said?.ok ? (
            <>
              <Row label="time" value={asClock(said.seconds)} />
              {said.grams ? (
                <Row label="filament" value={`${said.grams} g  ·  ${said.filament_cm3} cm³`} />
              ) : (
                <>
                  <Row label="filament" value={`${said.filament_cm3} cm³`} />
                  <Mono size="micro" color={core.dim}>
                    no weight: this material has no density recorded, and the slicer will not
                    invent one
                  </Mono>
                </>
              )}
              <Mono size="micro" color={core.dim} numberOfLines={2}>
                {said.name}
                {said.density_source ? `  ·  density: ${said.density_source}` : ''}
              </Mono>
            </>
          ) : (
            <>
              <Button
                label={slicing ? 'slicing…' : 'work out time and filament'}
                onPress={slice}
                disabled={slicing}
              />
              <Mono size="micro" color={core.dim}>
                {facts.for_the_slicer}
              </Mono>
            </>
          )}

          <Quiet label="open it ›" color={core.phosphor} onPress={() => onPart(part.dir)} />
        </>
      ) : null}
    </Panel>
  );
}

/**
 * Seconds as something a person reads. "1972 s" is a figure nobody can hold.
 */
function asClock(seconds: number | null | undefined): string {
  if (!seconds) return '—';
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.round((total % 3600) / 60);
  if (!hours) return `${minutes} min`;
  return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
}


interface Props {
  api: Api;
  health: Health | null;
  checking: boolean;
  problem: string | null;
  /** What the engine is doing, from the shared feed. */
  jobs: MachineJob[];
  /** Tapping something that is running goes and watches it. */
  onWatch: (jobId: string, request: string) => void;
  /** Ask the machine again at whatever address is in force. */
  onRetry: () => void;
  base: string;
  onBase: (next: string) => void;
  material: string | null;
  onMaterial: (name: string) => void;
  /**
   * The newest thing in the library, which is what this screen offers to
   * print.
   *
   * FOLLOWING ON FROM THE MODEL THAT WAS JUST MADE, which is the whole point
   * of the tab: somebody describes a part, watches it build, and the next
   * question is always "can I print it and what will it cost me". Null until
   * the library has been read.
   */
  latest: LibraryPart | null;
  /** Open a part in full. */
  onPart: (dir: string) => void;
}

export function MachineScreen({
  api,
  health,
  checking,
  problem,
  jobs,
  onWatch,
  onRetry,
  base,
  onBase,
  material,
  onMaterial,
  latest,
  onPart,
}: Props) {
  // The field is a draft until it is applied. Rebuilding the Api on every
  // keystroke would fire a health check at "http://1", "http://19", and so on.
  const [typed, setTyped] = useState(base);
  const [bad, setBad] = useState<string | null>(null);

  useEffect(() => {
    setTyped(base);
  }, [base]);

  const apply = useCallback(() => {
    const cleaned = cleanBase(typed);
    if (!cleaned) {
      setBad('that is not an address - try 192.168.1.40:8765');
      return;
    }
    setBad(null);
    setTyped(cleaned);
    onBase(cleaned);
  }, [onBase, typed]);

  const printer = health?.printer as Record<string, unknown> | undefined;
  const bed = health?.bed as Record<string, unknown> | undefined;
  const settings = health?.print as Record<string, unknown> | undefined;
  const materials = health?.materials ?? [];
  const templates = health?.templates ?? [];
  const changed = cleanBase(typed) !== base;

  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {/* A SCREEN TITLE IS A HEADING, NOT A LABEL - prose, like the
            question on the landing screen. Mono is for the values under it. */}
        <Prose size="title" weight="bold" color={core.screen}>
          print
        </Prose>

        {/* WHAT IT WOULD TAKE TO PRINT THE LAST THING MADE.
            The tab used to be "the machine" and show only the connection and
            what the engine was doing - true, and not the question anybody
            opens it with. The question is "can I print this, will it fit, how
            long, how much filament", and every part of that answer is either
            measured already or comes from a slicer. */}
        {latest ? (
          <PrintPanel api={api} part={latest} onPart={onPart} />
        ) : null}

        {/* WHAT IT IS DOING, FIRST AND LIVE. This is the reason to open this
            tab. The strip is the same one the landing screen and the library
            draw, from the same 2.5s poll - one answer to "what is the machine
            doing", not three. */}
        {health ? <Working jobs={jobs} onWatch={onWatch} /> : null}

        {/* THE STATE FIRST, THEN THE CONTROL. A person opening this screen is
            almost always here because something is not connected, so the
            answer to "is it working" is the top line rather than something to
            scroll for. */}
        <Panel title="connection">
          {checking ? (
            <View style={styles.centre}>
              <Waiting caption={`asking ${base}`} size={96} />
            </View>
          ) : health ? (
            <Verdict state="pass" text={`connected to ${base}`} />
          ) : (
            <Verdict state="fail" text={`nothing answered at ${base}`} />
          )}

          {/* WHICH OF THE TWO ARRANGEMENTS IS IN FORCE, said out loud. One of
              them keeps the geometry off the network entirely and the other
              does not, and that is not a detail to leave somebody to work
              out from an IP address. */}
          {isLoopback(base) ? (
            <Prose size="body" color={core.dim}>
              This is the cable. The phone's own localhost is forwarded to your computer, so
              nothing crosses a network and nobody else can reach the engine.
            </Prose>
          ) : (
            <Prose size="body" color={pen.warn}>
              This is a network address, so the phone is reaching your computer over Wi-Fi. It
              works without a cable; it also means anything else on that network can reach the
              engine.
            </Prose>
          )}

          <Field
            label="address"
            value={typed}
            onChangeText={setTyped}
            onSubmitEditing={apply}
            placeholder={LOOPBACK}
            keyboardType="url"
            note={
              'Plugged in by USB, leave this alone and run `adb reverse tcp:8765 tcp:8765` on the ' +
              'computer. On Wi-Fi, type the computer’s address - the port is filled in.'
            }
          />
          {bad ? <Verdict state="fail" text={bad} /> : null}

          <View style={styles.actions}>
            <Button
              label={changed ? 'use this address' : 'try again'}
              primary={changed}
              onPress={changed ? apply : onRetry}
              style={styles.grow}
            />
            {!isLoopback(base) ? (
              <Button label="back to the cable" onPress={() => onBase(LOOPBACK)} />
            ) : null}
          </View>

          {problem && !health ? <Problem text={problem} /> : null}
        </Panel>

        {/* Everything below needs an answer from the machine. Drawing empty
            panels with dashes in them would look like a machine that answered
            and had nothing, which is a different fault. */}
        {!health ? (
          <Empty
            title="the rest of this reads off the machine"
            hint="Once it answers, this screen shows the printer, the bed, the materials and the model it is running."
          />
        ) : (
          <>
            <Panel title="what it can do">
              <Row label="capability" value={health.capability?.tier ?? 'unknown'} />
              {health.capability?.headline ? (
                <Prose size="body" color={core.dim}>
                  {health.capability.headline}
                </Prose>
              ) : null}
              <Row
                label="model"
                value={health.model?.ok ? 'ready' : (health.model?.message ?? 'none')}
                valueColor={health.model?.ok ? pen.pass : core.dim}
              />
              {/* RULE 11 ON THE SCREEN: the system stays fully usable with no
                  model. A model that is not there is a smaller product, not a
                  broken one, and saying which is which stops somebody
                  concluding the app is down. */}
              {!health.model?.ok ? (
                <Prose size="body" color={core.dim}>
                  With no model, whittle still builds anything a spec file describes - the words
                  are what need one.
                </Prose>
              ) : null}
            </Panel>

            <Panel title="printer">
              {printer && Object.keys(printer).length ? (
                Object.entries(printer).map(([key, value]) => (
                  <Row key={key} label={key.replace(/_/g, ' ')} value={show(value)} />
                ))
              ) : (
                <Verdict state="warn" text="no printer in the machine's profile" />
              )}
            </Panel>

            <Panel title="print settings">
              {/* THE NOZZLE IS THE NUMBER EVERY FEATURE CHECK IS READ
                  AGAINST. A stored verdict records the nozzle it was taken
                  with, and the part screen compares the two - so this is the
                  other half of that comparison, and the app had no way to
                  show it. */}
              {settings && Object.keys(settings).length ? (
                Object.entries(settings).map(([key, value]) => (
                  <Row key={key} label={key.replace(/_/g, ' ')} value={show(value)} />
                ))
              ) : (
                <Verdict
                  state="warn"
                  text="this engine does not report its nozzle - it predates the field"
                />
              )}
            </Panel>

            <Panel title="bed">
              {/* RULE 29 REACHES THE SCREEN. An unmeasured value is UNSET in
                  the config and reading it raises, so the app says the bed is
                  not configured rather than drawing a default one - and the
                  bed check is what decides whether a part fits. */}
              {bed && bed.width_mm !== undefined ? (
                <>
                  <Row
                    label="size"
                    value={`${show(bed.width_mm)} × ${show(bed.depth_mm)} × ${show(bed.height_mm)} mm`}
                  />
                  {Object.entries(bed)
                    .filter(([key]) => !['width_mm', 'depth_mm', 'height_mm'].includes(key))
                    .map(([key, value]) => (
                      <Row key={key} label={key.replace(/_/g, ' ')} value={show(value)} />
                    ))}
                </>
              ) : (
                <Verdict
                  state="warn"
                  text="no bed configured - the does-it-fit check cannot run"
                />
              )}
            </Panel>

            <Panel title="material">
              <Prose size="body" color={core.dim}>
                What new parts are asked for in. These are the machine's own, and the choice is
                remembered between launches.
              </Prose>
              {materials.length ? (
                <View style={styles.chips}>
                  {materials.map((name) => (
                    <Chip
                      key={name}
                      label={name}
                      active={name === (material ?? health.material_default)}
                      onPress={() => onMaterial(name)}
                    />
                  ))}
                </View>
              ) : (
                <Verdict state="warn" text="the machine's profile lists no materials" />
              )}
            </Panel>

            <Panel title="templates it has pinned">
              {/* RULE 31, WHERE SOMEBODY MIGHT MISREAD IT. This is a fact
                  about the machine, not a menu: a template is an optimisation
                  for a shape that comes up often, and the making screen
                  deliberately offers none of them. It is here so the count is
                  knowable, and the sentence under it says what the count
                  means. */}
              <Prose size="body" color={core.dim}>
                Shortcuts for shapes that come up often, with bounds a builder can enforce.
                Nothing is limited to this list - anything else gets composed, which is the
                normal case rather than the fallback.
              </Prose>
              {/* PLAIN TEXT, NOT CHIPS. These were drawn as chips with an
                  empty onPress, so the screen offered a control that looked
                  pressable and did nothing - which is worse than showing
                  nothing, because a person presses it and concludes the app
                  is broken. They are a fact about the machine, so they are
                  set as one. */}
              {templates.length ? (
                <Mono size="label" color={core.screen} style={styles.list}>
                  {templates.join(', ')}
                </Mono>
              ) : (
                <Prose size="body" color={core.dim}>
                  none registered.
                </Prose>
              )}
            </Panel>

            <Panel title="versions">
              {/* These are cache keys, and they are the reason a stale picture
                  is not a mystery: a frame's URL carries the render version
                  and a GLB carries the mesh version, so changing the renderer
                  changes every frame's content without changing its URL. */}
              <Row label="app talks to" value={api.base} />
              {health.render_version !== undefined ? (
                <Row label="renders" value={String(health.render_version)} />
              ) : null}
              {health.mesh_version !== undefined ? (
                <Row label="meshes" value={String(health.mesh_version)} />
              ) : null}
            </Panel>
          </>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}


/**
 * What the engine is doing this second, and what it just finished.
 *
 * THE ENGINE'S OWN LAST WORD, not a stage this screen decided a job must be
 * at. `note` is the most recent thing the build actually said - "no template
 * fits - composing from primitives", "verify: passed" - and the elapsed time
 * is the server's clock, so a phone that was asleep for a minute shows the
 * truth rather than its own count.
 *
 * IDLE IS A STATE WORTH DRAWING. An empty panel reads as a panel that failed
 * to load; "nothing running" with the totals beside it reads as a machine
 * waiting for work, which is what it is.
 */
function Working({
  jobs,
  onWatch,
}: {
  jobs: MachineJob[];
  onWatch: (jobId: string, request: string) => void;
}) {
  const running = jobs.filter((job) => !job.done);
  const finished = jobs.filter((job) => job.done).slice(0, 4);

  return (
    <Panel title={running.length ? 'working now' : 'the engine'}>
      {running.length ? (
        running.map((job) => (
          <Pressable key={job.id} onPress={() => onWatch(job.id, job.request)}>
            <Surface step="well" style={styles.job}>
              <View style={styles.jobHead}>
                <Mono size="label" weight="medium" numberOfLines={1} style={styles.grow}>
                  {job.request || job.kind}
                </Mono>
                <Mono size="micro" color={core.phosphor}>
                  {Math.round(job.elapsed_s)}s
                </Mono>
              </View>
              <Mono size="micro" color={core.dim} numberOfLines={1}>
                {job.kind} · {job.note || 'starting'}
              </Mono>
            </Surface>
          </Pressable>
        ))
      ) : (
        <View style={styles.idle}>
          <View style={[styles.dot, { backgroundColor: pen.pass }]} />
          <Mono size="label" color={core.dim}>
            idle - nothing building
          </Mono>
        </View>
      )}

      {finished.length ? (
        <>
          <Mono size="micro" color={core.dim} style={styles.sinceHead}>
            just finished
          </Mono>
          {finished.map((job) => (
            <View key={job.id} style={styles.done}>
              <Mono size="micro" color={job.ok ? pen.pass : pen.fail}>
                {job.ok ? 'ok' : 'no'}
              </Mono>
              <Mono size="micro" color={core.dim} numberOfLines={1} style={styles.grow}>
                {job.request || job.kind}
              </Mono>
              <Mono size="micro" color={core.dim}>
                {Math.round(job.elapsed_s)}s
              </Mono>
            </View>
          ))}
        </>
      ) : null}
    </Panel>
  );
}

/**
 * One config value as a string, without inventing a precision.
 *
 * The printer and bed blocks are rendered straight off whatever the machine's
 * profile holds rather than a field list written here, because a client with
 * its own list stops showing a key the day somebody adds one. That means the
 * values arrive as unknowns.
 */
function show(value: unknown): string {
  if (value === null || value === undefined) return 'not set';
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
  }
  if (Array.isArray(value)) return value.map(show).join(' × ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
  },
  body: {
    padding: space.base,
    gap: space.base,
    paddingBottom: space.room,
  },
  centre: {
    alignItems: 'center',
    paddingVertical: space.snug,
  },
  actions: {
    flexDirection: 'row',
    gap: space.snug,
    paddingTop: space.tight,
  },
  grow: {
    flex: 1,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.tight,
  },
  job: {
    padding: space.snug,
    gap: space.hair,
    marginTop: space.tight,
  },
  jobHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  idle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
    paddingVertical: space.tight,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  sinceHead: {
    paddingTop: space.snug,
  },
  done: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
    paddingVertical: space.hair,
  },
  list: {
    lineHeight: 12 * 1.6,
  },
});
