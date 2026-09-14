/**
 * The editing screen: the model, the stack that made it, and the verdict.
 *
 * Build plan v8 section 13.3. The layout is the viewport with everything else
 * under it, because a phone in portrait has one column and the geometry is the
 * thing being looked at.
 *
 * THE THREE THINGS A PERSON NEEDS TO KNOW, and the three tabs:
 *
 *   model   what arrived - size, format, units, what the repair changed
 *   edits   what has been done to it, every step still a slider
 *   checks  whether it prints, and what to do about it if not
 *
 * WHAT MAKES THE DRAG USABLE
 * --------------------------
 * `final` is pointer-up. While the thumb is down the server rebuilds the
 * geometry and skips the printability gate - 43 ms a move against 488 ms - and
 * the verdict catches up when the finger lifts. In between, the checks tab
 * says the verdict is stale rather than showing a tick that describes the
 * previous value, which is worse than showing nothing.
 */

import Slider from '@react-native-community/slider';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import {
  ApiError,
  type Api,
  type Catalogue,
  type Edit as EditOp,
  type Parameter,
  type Project,
} from '../api';
import { core, metric, pen, radius, space, type } from '../tokens';
import { Button, Mono, Panel, Problem, Prose, Row, Segmented, Surface, Verdict } from '../ui';
import { Rig } from '../Rig';
import { Viewport } from '../Viewport';

const TABS = ['model', 'edits', 'checks'] as const;
type Tab = (typeof TABS)[number];

interface Props {
  api: Api;
  project: Project;
  onProject: (project: Project) => void;
  onClose: () => void;
}

export function EditScreen({ api, project, onProject, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('checks');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [glb, setGlb] = useState<ArrayBuffer | null>(null);
  const [simplified, setSimplified] = useState(false);
  const [sentence, setSentence] = useState('');
  const [echo, setEcho] = useState<string | null>(null);

  // Bumped on every change to the geometry. The preview follows this rather
  // than the project object, so a report refresh that changed no geometry does
  // not pull a GLB down the wire again.
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    api
      .catalogue()
      .then(setCatalogue)
      .catch(() => setCatalogue(null));
  }, [api]);

  // -- the preview --------------------------------------------------------

  const inFlight = useRef(false);
  const pending = useRef(false);

  const fetchPreview = useCallback(async () => {
    // ONE AT A TIME, AND ALWAYS THE LAST ONE. A drag fires faster than the
    // round trip completes; letting them queue would draw the model at every
    // position it passed through, seconds after the finger stopped. So a
    // request in flight sets a flag and the newest state is fetched once it
    // lands.
    if (inFlight.current) {
      pending.current = true;
      return;
    }
    inFlight.current = true;
    try {
      const { glb: bytes, simplified: proxy } = await api.preview(project.id);
      setGlb(bytes);
      setSimplified(proxy);
    } catch (error: any) {
      setProblem(String(error?.message ?? error));
    } finally {
      inFlight.current = false;
      if (pending.current) {
        pending.current = false;
        fetchPreview();
      }
    }
  }, [api, project.id]);

  useEffect(() => {
    fetchPreview();
  }, [fetchPreview, revision]);

  // -- changing things ----------------------------------------------------

  /**
   * Run one call against the server and keep the screen honest about it.
   *
   * `geometry` says whether what came back changes what is drawn. A toggle
   * does; asking the catalogue does not.
   */
  const run = useCallback(
    async <T,>(
      work: () => Promise<T>,
      take: (result: T) => Project | null,
      options: { geometry?: boolean; showBusy?: boolean } = {},
    ) => {
      const { geometry = true, showBusy = true } = options;
      if (showBusy) setBusy(true);
      setProblem(null);
      try {
        const result = await work();
        const next = take(result);
        if (next) onProject(next);
        if (geometry) setRevision((n) => n + 1);
        return result;
      } catch (error: any) {
        // A REFUSAL IS AN ANSWER. The server's 422 already says which wall was
        // too thick and why; showing "request failed" instead throws away the
        // only part worth reading.
        setProblem(
          error instanceof ApiError && error.isRefusal
            ? error.message
            : String(error?.message ?? error),
        );
        return null;
      } finally {
        if (showBusy) setBusy(false);
      }
    },
    [onProject],
  );

  const setValue = useCallback(
    (op: EditOp, parameter: Parameter, value: unknown, final: boolean) =>
      run(
        () => api.setValue(project.id, op.id, parameter.name, value, final),
        (r) => r.project,
        // No spinner mid-drag: a control that flickers busy on every frame is
        // less usable than one that simply keeps up.
        { showBusy: final },
      ),
    [api, project.id, run],
  );

  const say = useCallback(async () => {
    const text = sentence.trim();
    if (!text) return;
    const result = await run(
      () => api.say(project.id, text),
      (r) => r.project,
    );
    if (result) {
      setSentence('');
      setEcho(describeSaid(result));
    }
  }, [api, project.id, run, sentence]);

  // -- the screen ---------------------------------------------------------

  const verdict = project.report;
  const failures = verdict.findings.filter((f) => f.severity === 'fail');
  const state = verdict.stale ? 'waiting' : verdict.printable ? 'pass' : 'fail';
  const headline = verdict.stale
    ? 'checking the change'
    : verdict.printable
      ? 'this prints'
      : `${failures.length} thing${failures.length === 1 ? '' : 's'} stop it printing`;

  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={styles.header}>
        <Pressable onPress={onClose} hitSlop={space.base} style={styles.back}>
          <Mono size="label" color={core.dim}>
            ‹ library
          </Mono>
        </Pressable>
        <View style={styles.headerText}>
          <Mono size="label" weight="medium" numberOfLines={1}>
            {project.name}
          </Mono>
          <Mono size="micro" color={core.dim}>
            {project.size_mm.map((v) => v.toFixed(1)).join(' × ')} mm ·{' '}
            {project.triangles.toLocaleString()} triangles
          </Mono>
        </View>
        {busy ? <Rig size={40} /> : null}
      </View>

      <View style={styles.viewport}>
        <Viewport glb={glb} simplified={simplified} placeholder="drawing the model…" />
      </View>

      <Surface step="pill" style={styles.verdictBar}>
        <Verdict state={state} text={headline} />
      </Surface>

      <Segmented options={TABS} value={tab} onChange={setTab} style={styles.tabs} />

      <ScrollView
        style={styles.sheet}
        contentContainerStyle={styles.sheetBody}
        keyboardShouldPersistTaps="handled">
        {problem ? <Problem text={problem} /> : null}

        {tab === 'model' ? <ModelTab project={project} /> : null}
        {tab === 'edits' ? (
          <EditsTab
            project={project}
            catalogue={catalogue}
            onSet={setValue}
            onToggle={(op) =>
              run(
                () => api.toggle(project.id, op.id, !op.enabled),
                (r) => r.project,
              )
            }
            onRemove={(op) =>
              run(
                () => api.remove(project.id, op.id),
                (r) => r.project,
              )
            }
            onAdd={(kind) =>
              run(
                () => api.addEdit(project.id, kind),
                (r) => r.project,
              )
            }
          />
        ) : null}
        {tab === 'checks' ? <ChecksTab project={project} /> : null}
      </ScrollView>

      {echo ? (
        <Surface step="well" style={styles.echo}>
          <Prose size="body" color={core.dim}>
            {echo}
          </Prose>
        </Surface>
      ) : null}

      <Surface step="pill" style={styles.command}>
        <TextInput
          value={sentence}
          onChangeText={setSentence}
          onSubmitEditing={say}
          returnKeyType="send"
          placeholder="hollow it to 2mm and cut it to fit my bed"
          placeholderTextColor={core.dim}
          style={styles.input}
        />
        <Button label="do it" primary onPress={say} disabled={!sentence.trim() || busy} />
      </Surface>
    </KeyboardAvoidingView>
  );
}

/**
 * What the language layer understood, in the words it used.
 *
 * Section 12 is explicit that an instruction it could not map is surfaced
 * every time - "pretending otherwise is how trust dies" - so `unmapped` and
 * the questions are shown, not just the operations that landed.
 */
function describeSaid(said: { echo: string; unmapped: string[]; questions: any[] }): string {
  const lines = [said.echo];
  for (const question of said.questions) {
    lines.push(`${question.prompt} — ${question.options.join(' · ')}`);
  }
  if (said.unmapped.length) {
    lines.push(`ignored: ${said.unmapped.join('; ')}`);
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// what arrived
// ---------------------------------------------------------------------------

function ModelTab({ project }: { project: Project }) {
  const units = project.units;
  return (
    <>
      <Panel title="the file">
        <Row label="name" value={project.name} />
        <Row label="format" value={project.format} />
        <Row label="triangles" value={project.triangles.toLocaleString()} />
        <Row label="separate bodies" value={String(project.bodies)} />
        <Row label="size" value={`${project.size_mm.map((v) => v.toFixed(1)).join(' × ')} mm`} />
      </Panel>

      <Panel title="units">
        {/* AN ASSUMPTION IS LABELLED AS ONE. An STL carries no units, so a
            number here is a guess with a reason, and the other readings are
            shown so it can be corrected rather than argued with. */}
        <Row
          label={units.assumed ? 'assumed' : 'declared'}
          value={units.units}
          valueColor={units.assumed ? pen.warn : core.screen}
        />
        <Prose size="body" color={core.dim}>
          {units.reason}
        </Prose>
        {units.alternatives.length ? (
          <View style={styles.alternatives}>
            {units.alternatives.map((alt) => (
              <Row
                key={alt.units}
                label={`as ${alt.units}`}
                value={`${alt.size_mm} mm across`}
              />
            ))}
          </View>
        ) : null}
      </Panel>

      <Panel title="repair">
        {project.repair.changed ? (
          project.repair.steps.map((step, index) => (
            <Prose key={index} size="body" color={core.screen}>
              · {step}
            </Prose>
          ))
        ) : (
          <Prose size="body" color={core.dim}>
            nothing needed fixing.
          </Prose>
        )}
        {project.repair.unresolved.map((item, index) => (
          <Verdict key={index} state="warn" text={item} />
        ))}
      </Panel>
    </>
  );
}

// ---------------------------------------------------------------------------
// the stack
// ---------------------------------------------------------------------------

function EditsTab({
  project,
  catalogue,
  onSet,
  onToggle,
  onRemove,
  onAdd,
}: {
  project: Project;
  catalogue: Catalogue | null;
  onSet: (op: EditOp, parameter: Parameter, value: unknown, final: boolean) => void;
  onToggle: (op: EditOp) => void;
  onRemove: (op: EditOp) => void;
  onAdd: (kind: string) => void;
}) {
  const already = new Set(project.edits.map((op) => op.kind));

  return (
    <>
      {project.edits.length === 0 ? (
        <Panel>
          <Prose size="body" color={core.dim}>
            Nothing has been done to this model yet. Add a step below, or say what you want in
            the line at the bottom.
          </Prose>
        </Panel>
      ) : null}

      {project.edits.map((op) => (
        <Panel key={op.id}>
          <View style={styles.opHead}>
            <View style={styles.opTitle}>
              <Mono size="label" weight="medium" color={op.enabled ? core.screen : core.dim}>
                {op.kind}
              </Mono>
              <Prose size="body" color={core.dim}>
                {op.summary}
              </Prose>
            </View>
            <View style={styles.opActions}>
              <Button label={op.enabled ? 'on' : 'off'} onPress={() => onToggle(op)} />
              <Button label="remove" onPress={() => onRemove(op)} />
            </View>
          </View>

          {op.parameters.map((parameter) => (
            <ParameterControl
              key={parameter.name}
              parameter={parameter}
              disabled={!op.enabled}
              onChange={(value, final) => onSet(op, parameter, value, final)}
            />
          ))}
        </Panel>
      ))}

      <Panel title="add a step">
        {/* THE LIST COMES FROM THE SERVER. /api/operations is the registry
            itself, so a client cannot offer an operation the engine has never
            heard of, nor quietly stop offering one that was added. */}
        {catalogue ? (
          <View style={styles.chips}>
            {catalogue.operations.map((entry) => (
              <Pressable
                key={entry.kind}
                onPress={() => onAdd(entry.kind)}
                style={[styles.chip, already.has(entry.kind) && styles.chipUsed]}>
                <Mono size="label" color={core.screen}>
                  {entry.kind}
                </Mono>
              </Pressable>
            ))}
          </View>
        ) : (
          <Prose size="body" color={core.dim}>
            could not read the operation list from the machine.
          </Prose>
        )}
        {catalogue?.not_built_yet.length ? (
          <Prose size="body" color={core.dim}>
            not built yet: {catalogue.not_built_yet.join(', ')}
          </Prose>
        ) : null}
      </Panel>
    </>
  );
}

/**
 * One parameter, drawn as whatever it actually is.
 *
 * `slidable` is the server's own word for "has both ends and is a number" -
 * see Parameter.slidable - so a control is never guessed at from the name. A
 * length without bounds gets a readout rather than a slider whose ends would
 * be invented here, which rule 29 forbids in the engine and which would be no
 * better in the client.
 */
function ParameterControl({
  parameter,
  disabled,
  onChange,
}: {
  parameter: Parameter;
  disabled: boolean;
  onChange: (value: unknown, final: boolean) => void;
}) {
  // The live value while a finger is down. The server is authoritative and
  // clamps, but waiting for the round trip to move the thumb makes the slider
  // feel broken.
  const [dragging, setDragging] = useState<number | null>(null);
  const shown = dragging ?? parameter.value;

  if (parameter.kind === 'bool') {
    return (
      <View style={styles.parameter}>
        <Mono size="label" color={core.dim}>
          {parameter.name}
        </Mono>
        <Button
          label={parameter.value ? 'yes' : 'no'}
          disabled={disabled}
          onPress={() => onChange(!parameter.value, true)}
        />
      </View>
    );
  }

  if (parameter.kind === 'choice' || parameter.kind === 'axis') {
    return (
      <View style={styles.parameterBlock}>
        <Mono size="label" color={core.dim}>
          {parameter.name}
        </Mono>
        <Segmented
          options={parameter.choices}
          value={String(parameter.value)}
          onChange={(next) => onChange(next, true)}
        />
      </View>
    );
  }

  const numeric = typeof shown === 'number' ? shown : Number(shown);
  const readout = `${Number.isFinite(numeric) ? numeric.toFixed(2) : String(shown)}${
    parameter.units ? ` ${parameter.units}` : ''
  }`;

  return (
    <View style={styles.parameterBlock}>
      <Row label={parameter.name} value={readout} valueColor={core.phosphor} />
      {parameter.description ? (
        <Prose size="body" color={core.dim}>
          {parameter.description}
        </Prose>
      ) : null}

      {parameter.slidable ? (
        <>
          <Slider
            disabled={disabled}
            minimumValue={parameter.low!}
            maximumValue={parameter.high!}
            value={typeof parameter.value === 'number' ? parameter.value : 0}
            step={parameter.kind === 'count' ? 1 : 0}
            minimumTrackTintColor={core.phosphor}
            maximumTrackTintColor={core.etch}
            thumbTintColor={core.phosphor}
            onValueChange={(value) => {
              setDragging(value);
              onChange(value, false);
            }}
            onSlidingComplete={(value) => {
              setDragging(null);
              onChange(value, true);
            }}
          />
          {/* THE ENDS, WRITTEN DOWN. Section 10 clamps the slider so the
              failure cannot happen; showing where it stops is what turns that
              from a control that mysteriously will not move into one whose
              limits are part of the answer. */}
          <View style={styles.bounds}>
            <Mono size="micro" color={core.dim}>
              {parameter.low!.toFixed(2)}
            </Mono>
            <Mono size="micro" color={core.dim}>
              {parameter.high!.toFixed(2)}
            </Mono>
          </View>
        </>
      ) : (
        <Mono size="micro" color={core.dim}>
          no bounds for this one, so there is no slider to drag
        </Mono>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// whether it prints
// ---------------------------------------------------------------------------

function ChecksTab({ project }: { project: Project }) {
  const report = project.report;
  const failures = report.findings.filter((f) => f.severity === 'fail');
  const warnings = report.findings.filter((f) => f.severity !== 'fail');

  return (
    <>
      {report.stale ? (
        <Panel>
          {/* NOT A TICK FROM THE LAST VALUE. The gate does not run while a
              thumb is down, and saying so is the honest version of a verdict
              that has not caught up yet. */}
          <Verdict state="waiting" text="the model moved - re-checking when you let go" />
        </Panel>
      ) : null}

      {failures.length === 0 && warnings.length === 0 && !report.stale ? (
        <Panel>
          <Verdict state="pass" text="every check passed" />
        </Panel>
      ) : null}

      {[...failures, ...warnings].map((finding, index) => (
        <Panel key={index} title={finding.rule}>
          <Verdict state={finding.severity === 'fail' ? 'fail' : 'warn'} text={finding.detail} />
          {finding.fix ? (
            <Prose size="body" color={core.dim}>
              {finding.fix}
            </Prose>
          ) : null}
        </Panel>
      ))}

      <Panel title="measured">
        {Object.entries(report.measurements).map(([key, value]) => (
          <Row key={key} label={key} value={formatMeasurement(value)} />
        ))}
      </Panel>
    </>
  );
}

/** A measurement as the engine gave it, without inventing a precision. */
function formatMeasurement(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(3);
  }
  if (Array.isArray(value)) {
    return value.map((v) => formatMeasurement(v)).join(' × ');
  }
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  return String(value);
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    gap: space.snug,
    padding: space.base,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.base,
  },
  back: {
    paddingVertical: space.tight,
  },
  headerText: {
    flex: 1,
  },
  viewport: {
    flex: 1,
    minHeight: 220,
    borderRadius: radius.card,
    overflow: 'hidden',
  },
  verdictBar: {
    paddingHorizontal: space.base,
    paddingVertical: space.snug,
  },
  tabs: {},
  sheet: {
    maxHeight: '42%',
  },
  sheetBody: {
    gap: space.snug,
    paddingBottom: space.snug,
  },
  alternatives: {
    marginTop: space.tight,
  },
  opHead: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: space.snug,
  },
  opTitle: {
    flex: 1,
  },
  opActions: {
    flexDirection: 'row',
    gap: space.tight,
  },
  parameter: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.base,
    paddingTop: space.snug,
  },
  parameterBlock: {
    paddingTop: space.snug,
    gap: space.tight,
  },
  bounds: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.tight,
  },
  chip: {
    minHeight: metric.tap - space.base,
    justifyContent: 'center',
    paddingHorizontal: space.base,
    borderRadius: radius.control,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: core.etch,
  },
  chipUsed: {
    borderColor: core.phosphor,
  },
  echo: {
    padding: space.snug,
  },
  command: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
    padding: space.snug,
  },
  input: {
    flex: 1,
    minHeight: metric.tap,
    color: core.screen,
    fontFamily: type.mono,
    fontSize: type.size.body,
    paddingHorizontal: space.snug,
  },
});
