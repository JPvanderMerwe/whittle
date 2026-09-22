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
 *   save    the edited mesh, written to a folder on the phone
 *
 * THE FOURTH TAB IS NEW AND IT CLOSES A HOLE THE APP HAD EVERYWHERE: there
 * was no way to get a model out of it. You could import an STL, repair it,
 * hollow it, cut it to fit the bed, watch every check pass - and the result
 * stayed on the machine. `/api/project/<id>/export.stl` has always existed.
 * The export is the full mesh and never the preview proxy, which is why the
 * viewport says which one it is drawing.
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
  type Said,
} from '../api';
import { FORMAT_NOTE, SAVEABLE, saveName, saveToFolder } from '../save';
import { meshTweaks, operationLabel } from '../tweaks';
import { core, metric, pen, radius, space, type } from '../tokens';
import {
  Button,
  Chip,
  Empty,
  Header,
  Mono,
  Panel,
  Problem,
  Prose,
  Quiet,
  Row,
  Segmented,
  Surface,
  Verdict,
} from '../ui';
import { Rig } from '../Rig';
import { Viewport } from '../Viewport';

const TABS = ['change it', 'model', 'checks', 'save'] as const;
type Tab = (typeof TABS)[number];

interface Props {
  api: Api;
  project: Project;
  onProject: (project: Project) => void;
  onClose: () => void;
}

export function EditScreen({ api, project, onProject, onClose }: Props) {
  // THE CHANGE TAB LEADS, as it does on a built part. Somebody who has just
  // imported a model is here to do something to it; the verdict is one line at
  // the top whichever tab is open.
  const [tab, setTab] = useState<Tab>('change it');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [glb, setGlb] = useState<ArrayBuffer | null>(null);
  const [simplified, setSimplified] = useState(false);
  const [sentence, setSentence] = useState('');
  /** What the language layer made of the last sentence. See Understood. */
  const [echo, setEcho] = useState<Said | null>(null);
  /** The last thing a save did, said back. */
  const [saved, setSaved] = useState<string | null>(null);

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
      setEcho(result);
    }
  }, [api, project.id, run, sentence]);

  const save = useCallback(
    async (format: 'stl' | 'glb') => {
      setBusy(true);
      setProblem(null);
      setSaved(null);
      const result = await saveToFolder(
        api.exportUrl(project.id, format),
        saveName(project.name.replace(/\.[^.]+$/, ''), format),
        // GLB IS NOT IN THE SERVER'S PART ALLOW-LIST because that list is for
        // files sitting in a part's directory; a project export is generated.
        // So the type is named here rather than looked up and missed.
        format === 'stl' ? SAVEABLE.stl : 'model/gltf-binary',
      );
      setBusy(false);
      if (result.ok) {
        setSaved(`${saveName(project.name.replace(/\.[^.]+$/, ''), format)} saved to ${result.where}`);
      } else if (!result.cancelled) {
        setProblem(result.message);
      }
    },
    [api, project.id, project.name],
  );

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
      {/* The back label used to say "library" and did not go there. A word
          on a back arrow is a promise about where it lands. */}
      <Header
        back={onClose}
        backLabel="back"
        title={project.name}
        subtitle={
          `${project.size_mm.map((v) => v.toFixed(1)).join(' × ')} mm · ` +
          `${project.triangles.toLocaleString()} triangles`
        }
        right={busy ? <Rig size={40} /> : undefined}
      />

      <View style={styles.viewport}>
        <Viewport glb={glb} simplified={simplified} placeholder="drawing the model…" />
      </View>

      <Surface step="pill" style={styles.verdictBar}>
        <Verdict state={state} text={headline} />
      </Surface>

      <Segmented options={TABS} value={tab} onChange={setTab} />

      <ScrollView
        style={styles.sheet}
        contentContainerStyle={styles.sheetBody}
        keyboardShouldPersistTaps="handled">
        {problem ? <Problem text={problem} /> : null}

        {tab === 'model' ? <ModelTab project={project} /> : null}
        {tab === 'change it' ? (
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
            onSay={setSentence}
          />
        ) : null}
        {tab === 'checks' ? <ChecksTab project={project} /> : null}
        {tab === 'save' ? (
          <SaveTab project={project} onSave={save} busy={busy} saved={saved} />
        ) : null}
      </ScrollView>

      {echo ? <Understood said={echo} onDismiss={() => setEcho(null)} /> : null}

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
 * What the language layer made of the sentence - including the part it did not.
 *
 * RULE 32'S THIRD REQUIREMENT, AND IT IS NOT OPTIONAL: "what was not
 * understood is said out loud, every time... an instruction that mapped to
 * nothing is reported in the words the person used, with the real options
 * beside it. Silently doing three quarters of what was asked is how trust
 * dies, and it is worse here than anywhere else because the person cannot see
 * the parameter that was missed."
 *
 * This was three lines joined with newlines and drawn as one grey paragraph at
 * the same weight as every other hint on the screen. The half that landed and
 * the half that did not looked identical, which is the failure the rule names
 * with the formatting still technically present.
 *
 * So the three have three different voices: what was done is a pass, a
 * question is a question with its real options listed, and an instruction that
 * reached nothing is a warning in the person's own words.
 */
function Understood({ said, onDismiss }: { said: Said; onDismiss: () => void }) {
  return (
    <Surface step="card" style={styles.echo}>
      <View style={styles.echoHead}>
        <Mono size="micro" color={core.dim} style={styles.echoGrow}>
          what it did
        </Mono>
        <Pressable onPress={onDismiss} hitSlop={space.base}>
          <Mono size="micro" color={core.dim}>
            dismiss
          </Mono>
        </Pressable>
      </View>

      {said.echo ? <Verdict state="pass" text={said.echo} /> : null}

      {said.questions.map((question, index) => (
        <View key={index} style={styles.echoBlock}>
          <Verdict state="waiting" text={question.prompt} />
          {/* THE REAL OPTIONS BESIDE IT, which is the half of the rule that is
              easiest to drop: a question with no answers listed is a dead end
              for anybody who has not read the schema. */}
          {question.options.length ? (
            <Mono size="micro" color={core.dim}>
              {question.options.join('  ·  ')}
            </Mono>
          ) : null}
        </View>
      ))}

      {said.unmapped.length ? (
        <View style={styles.echoBlock}>
          {said.unmapped.map((text, index) => (
            <Verdict key={index} state="warn" text={`nothing matched "${text}"`} />
          ))}
          <Prose size="body" color={core.dim}>
            That part of the sentence changed nothing. Try naming a dimension - taller, wider,
            thicker - or use the sliders on the edits tab.
          </Prose>
        </View>
      ) : null}
    </Surface>
  );
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
  onSay,
}: {
  project: Project;
  catalogue: Catalogue | null;
  onSet: (op: EditOp, parameter: Parameter, value: unknown, final: boolean) => void;
  onToggle: (op: EditOp) => void;
  onRemove: (op: EditOp) => void;
  onAdd: (kind: string) => void;
  onSay: (sentence: string) => void;
}) {
  const already = new Set(project.edits.map((op) => op.kind));
  const suggestions = meshTweaks(catalogue);
  /** Which step's remove has been armed. One at a time, cleared on any other tap. */
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <>
      {/* WHAT TO SAY, FIRST. An empty box labelled "say what you want" works
          for somebody who already knows what the parser accepts, and this is
          the screen a person reaches by opening a file they downloaded - they
          have no idea what this thing can do to it. Every phrase here is one
          whittle/edit/intent.py actually matches. */}
      {suggestions.length ? (
        <Panel title={project.edits.length ? 'or say something else' : 'try saying'}>
          <Prose size="body" color={core.dim}>
            Tap one to put it in the box at the bottom, change the numbers if you like, then send
            it. It takes any sentence - these are the ones that come up.
          </Prose>
          <View style={styles.suggestions}>
            {suggestions.map((tweak) => (
              <Chip key={tweak.say} label={tweak.say} onPress={() => onSay(tweak.say)} />
            ))}
          </View>
        </Panel>
      ) : null}

      {project.edits.length === 0 ? (
        <Panel>
          <Empty
            title="nothing has been done to this model yet"
            hint="Say what you want in the box at the bottom, or add a step by hand below. Every step stays a slider you can drag afterwards - nothing here is one-shot."
          />
        </Panel>
      ) : null}

      {project.edits.map((op) => (
        <Panel key={op.id}>
          <View style={styles.opHead}>
            <View style={styles.opTitle}>
              {/* THE OPERATION'S NAME AS A PERSON WOULD SAY IT. The registry's
                  names are identifiers - `thicken_thin_walls` - and this
                  screen was printing them raw. Rule 32's split, on the one
                  screen where the operations ARE the interface. */}
              <Mono size="label" weight="medium" color={op.enabled ? core.screen : core.dim}>
                {operationLabel(op.kind)}
              </Mono>
              <Prose size="body" color={core.dim}>
                {op.summary}
              </Prose>
            </View>
            {/* A TOGGLE THAT READS AS ITS STATE, and a remove that cannot be
                hit by accident.

                These were two identical buttons side by side, one labelled
                "on" and one "remove" - so the control for "try it without this
                step" sat a thumb's width from the one that destroys the step,
                and the toggle looked like a command rather than a state. A
                step somebody spent five minutes tuning is not a thing to lose
                to a mistap. */}
            <View style={styles.opActions}>
              <Chip
                label={op.enabled ? 'on' : 'off'}
                active={op.enabled}
                onPress={() => onToggle(op)}
              />
              <Quiet
                label={confirming === op.id ? 'tap to confirm' : 'remove'}
                color={confirming === op.id ? pen.fail : core.dim}
                onPress={() => {
                  if (confirming === op.id) {
                    setConfirming(null);
                    onRemove(op);
                  } else {
                    setConfirming(op.id);
                  }
                }}
              />
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
          // A ROW OF IDENTIFIERS IS NOT A MENU. These were bare chips reading
          // `remove_floaters` and `thicken_thin_walls`, which tells somebody
          // what the function is called rather than what it does. The registry
          // carries a summary for every one of them and it was going unused.
          <View style={styles.steps}>
            {catalogue.operations.map((entry) => (
              <Pressable
                key={entry.kind}
                onPress={() => onAdd(entry.kind)}
                style={({ pressed }) => [{ opacity: pressed ? 0.7 : 1 }]}>
                <Surface
                  step="well"
                  style={[styles.step, already.has(entry.kind) && styles.stepUsed]}>
                  <View style={styles.stepHead}>
                    <Mono size="label" weight="medium" style={styles.stepName}>
                      {operationLabel(entry.kind)}
                    </Mono>
                    {already.has(entry.kind) ? (
                      <Mono size="micro" color={core.phosphor}>
                        on the stack
                      </Mono>
                    ) : null}
                  </View>
                  <Prose size="body" color={core.dim}>
                    {entry.summary}
                  </Prose>
                </Surface>
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
  // TWO DECIMALS ON A LENGTH, NONE ON A COUNT. `2.00 holes` is not a number
  // anybody writes, and `0.8 mm` with the trailing zero dropped stops reading
  // as a measurement - so the precision follows what the thing is.
  const figure = Number.isFinite(numeric)
    ? parameter.kind === 'count'
      ? String(Math.round(numeric))
      : numeric.toFixed(2)
    : String(shown);

  return (
    <View style={styles.parameterBlock}>
      {/* THE VALUE IS THE THING BEING ADJUSTED, so it is the biggest text in
          the block rather than the smallest. It was a label-sized figure on
          the right of a row, the same weight as the name beside it - on a
          screen whose entire purpose is moving that number. */}
      <View style={styles.parameterHead}>
        <Mono size="label" color={core.dim} style={styles.grow} numberOfLines={1}>
          {parameter.name.replace(/_mm$|_deg$/, '').replace(/_/g, ' ')}
        </Mono>
        <Mono size="figure" weight="medium" color={core.phosphor}>
          {figure}
        </Mono>
        {parameter.units ? (
          <Mono size="micro" color={core.dim}>
            {parameter.units}
          </Mono>
        ) : null}
      </View>
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
              {trimBound(parameter.low!)}
            </Mono>
            {/* THE ENDS ARE MEASURED OFF THIS MESH, which is worth saying once
                - a wall that stops at 2.67 mm stops there because that is what
                the geometry allows, not because somebody picked a round
                number. */}
            <Mono size="micro" color={core.dim}>
              {trimBound(parameter.high!)}
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

// ---------------------------------------------------------------------------
// taking it away
// ---------------------------------------------------------------------------

/**
 * The edited mesh, written to a folder on the phone.
 *
 * THE EXPORT IS NEVER THE PROXY. The viewport may be drawing a simplified copy
 * so a drag stays responsive on a 40 MB mesh, and the file written here is
 * built from the real stack - which is why the viewport says which of the two
 * it is showing rather than leaving somebody to wonder why the render and the
 * export disagree.
 *
 * SAVE WHILE A CHECK IS FAILING? YES, AND WITHOUT A WARNING DIALOGUE. The
 * checks tab already says in words what stops it printing, and a second
 * confirmation over the top of that is a product deciding it knows better than
 * the person holding the printer. Plenty of legitimate reasons exist to export
 * a mesh that this profile will not print: a different machine, a different
 * nozzle, or a part that is going to be cut up next.
 */
function SaveTab({
  project,
  onSave,
  busy,
  saved,
}: {
  project: Project;
  onSave: (format: 'stl' | 'glb') => void;
  busy: boolean;
  saved: string | null;
}) {
  const formats: { format: 'stl' | 'glb'; note: string }[] = [
    { format: 'stl', note: FORMAT_NOTE.stl },
    { format: 'glb', note: 'mesh with its materials - for a viewer, not a slicer' },
  ];

  return (
    <>
      {saved ? (
        <Panel>
          <Verdict state="pass" text={saved} />
        </Panel>
      ) : null}

      <Panel title="save it">
        <Prose size="body" color={core.dim}>
          Pick a folder on the phone and the file is written there. This is the full mesh with
          every step of the stack applied, not the preview.
        </Prose>
        {formats.map(({ format, note }) => (
          <View key={format} style={styles.saveRow}>
            <View style={styles.saveWhat}>
              <Mono size="label" weight="medium">
                {format.toUpperCase()}
              </Mono>
              <Mono size="micro" color={core.dim}>
                {note}
              </Mono>
            </View>
            <Button
              label="save"
              primary={format === 'stl'}
              onPress={() => onSave(format)}
              disabled={busy}
            />
          </View>
        ))}
      </Panel>

      {!project.report.printable && !project.report.stale ? (
        <Panel>
          {/* SAID, NOT BLOCKED. See the note above this component. */}
          <Verdict
            state="warn"
            text="a check is failing on this profile - the file still saves, and the checks tab says which"
          />
        </Panel>
      ) : null}
    </>
  );
}

/**
 * A bound as a person reads it.
 *
 * `2.6666666666666665` is what a bound derived from the mesh's own thickness
 * actually is, and printing it whole turns the one number that explains why a
 * slider stops into noise. Two decimals, trailing zeros gone.
 */
function trimBound(value: number): string {
  return String(Number(value.toFixed(2)));
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
  parameterHead: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: space.snug,
  },
  grow: {
    flex: 1,
  },
  bounds: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  suggestions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.tight,
  },
  steps: {
    gap: space.snug,
  },
  step: {
    padding: space.snug,
    gap: space.hair,
  },
  stepUsed: {
    borderColor: core.phosphor,
  },
  stepHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  stepName: {
    flex: 1,
  },
  echo: {
    padding: space.base,
    gap: space.snug,
  },
  echoHead: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  echoGrow: {
    flex: 1,
  },
  echoBlock: {
    gap: space.tight,
  },
  saveRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.base,
    paddingTop: space.tight,
  },
  saveWhat: {
    flex: 1,
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
