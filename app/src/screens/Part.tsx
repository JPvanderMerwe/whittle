/**
 * A built part: what it is, whether it prints, and how to get it out.
 *
 * Reached two ways - straight off a build, or out of the library - so it takes
 * a name and fetches the rest. The geometry goes through the SAME viewport the
 * imports use: one renderer, one GLB reader, one set of eyes on whether it
 * draws.
 *
 * WHAT WAS WRONG WITH THIS SCREEN, AND IT WAS NOT THE LAYOUT
 * ----------------------------------------------------------
 * It showed a name, a size, a piece count and one verdict word. Everything
 * else it drew came from `built` - the payload of a build that had JUST
 * happened - so a part opened from the library, which is the only way anybody
 * ever looks at one again, showed almost nothing. Meanwhile /api/part was
 * already serving:
 *
 *   checks.lines   every measured value with its status - watertight, worst
 *                  overhang in degrees, bed contact in mm2, feature sizes
 *   checks.drift   whether the printer profile has MOVED since that verdict
 *                  was taken, which is the difference between a verdict and a
 *                  stale one
 *   draft          why a part that never built did not build, in the engine's
 *                  own words - "disc in cut mode removed nothing; it sits at
 *                  (20.0, 0.0, -2.0)... set z_mm to -4.00"
 *   files          what is actually on disk to take away
 *
 * All of it was thrown away. So this is not a redesign of what was here, it is
 * the screen finally showing what the machine had already worked out.
 *
 * AND YOU CAN NOW TAKE THE PART WITH YOU. There was no download anywhere in
 * the app. See src/save.ts.
 *
 * THE VERDICT IS THE HEADLINE, and the problems are quoted in the engine's own
 * words. A part that failed verification still gets shown - it exists, it is on
 * disk, and hiding it would leave somebody with a build that "did nothing".
 * What it does not get is a green tick.
 */

import Slider from '@react-native-community/slider';
import React, { useCallback, useEffect, useState } from 'react';
import {
  Image,
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
  type Assumption,
  type BuiltPart,
  type CheckLine,
  type Checks,
  type PartDetail,
  type LibraryPart,
  type PartOption,
  type Project,
  type TemplateInfo,
} from '../api';
import {
  dimensionsFromOps,
  dimensionsOf,
  sayForAssumption,
  tweaksFor,
  type Dimension,
  type Tweak,
} from '../tweaks';
import { FORMAT_NOTE, SAVEABLE, saveName, saveToFolder } from '../save';
import { buildNumber, chainOf } from '../versions';
import { core, metric, pen, radius, space, type } from '../tokens';
import { Rig } from '../Rig';
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
import { Viewport } from '../Viewport';

const TABS = ['change it', 'checks', 'measured', 'report'] as const;

/**
 * What an IMPORTED mesh gets instead.
 *
 * No "change it": there is no spec, so the sentence has nothing to act on and
 * the sliders have no schema. What it does have is a mesh, which means every
 * check runs and every measurement is real - so those lead.
 */
const IMPORT_TABS = ['measured', 'checks', 'report'] as const;

/** The two orientations, in the words a person uses for them. */
const LAYOUTS = ['assembled', 'on the bed'] as const;
type Tab = (typeof TABS)[number];

interface Props {
  api: Api;
  /**
   * Every part in the library, so this screen can show where this one sits in
   * its own history.
   *
   * Passed in rather than fetched: the machine feed already holds it, and a
   * second read here would be a second answer to what has been made.
   */
  parts: LibraryPart[] | null;
  /** The part to show. Changing it reloads everything, which is how options work. */
  name: string;
  /** Present when we just built it; absent when it came out of the library. */
  built?: BuiltPart;
  onClose: () => void;
  /**
   * A change was asked for; watch it rebuild.
   *
   * The kind travels with it because the two cost wildly different amounts and
   * the watching screen promises different things about them - a refine may
   * reach the model and take minutes, setting a number never does.
   */
  onChanging: (jobId: string, instruction: string, kind: 'refine' | 'params') => void;
  /** Put sliders on it. */
  onEdit: (project: Project) => void;
  /** Open a different part - an earlier build of this one. */
  onShowPart: (dir: string) => void;
  /** It is gone: leave this screen and re-read the library. */
  onDeleted: () => void;
  /** Its directory changed, which is its identity - follow it. */
  onRenamed: (dir: string) => void;
}

export function PartScreen({
  api,
  parts,
  name,
  built,
  onClose,
  onChanging,
  onEdit,
  onShowPart,
  onDeleted,
  onRenamed,
}: Props) {
  const [instruction, setInstruction] = useState('');
  const [busy, setBusy] = useState(false);
  const [showing, setShowing] = useState(name);
  const [detail, setDetail] = useState<PartDetail | null>(null);
  const [glb, setGlb] = useState<ArrayBuffer | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  // THE CHANGE TAB OPENS FIRST, and that is the whole shape of this screen.
  // Somebody typed two words, the engine chose every number, and what they are
  // here to do is move those numbers - not read a verdict. The verdict is one
  // line at the top either way.
  const [tab, setTab] = useState<Tab>('change it');
  /**
   * Which of the part's two orientations the viewport shows.
   *
   * RULE 21: these are separate functions, not one rotated into the other. The
   * assembled form is what the GLB is and what a person recognises; the print
   * layout is what comes off the bed, and it is the one that decides whether
   * the thing is printable at all.
   */
  const [layout, setLayout] = useState<'assembled' | 'print'>('assembled');

  /**
   * Slider values that have moved but not been built yet.
   *
   * NOT SENT ON RELEASE. Each build is a real rebuild with every check at the
   * end of it - seconds, not milliseconds - so firing one per slider would
   * queue four rebuilds to change four numbers, and three of them would be
   * thrown away. They collect here and go in one request.
   */
  const [pending, setPending] = useState<Record<string, number>>({});

  /**
   * Managing the part itself: renaming it, or removing it.
   *
   * SHUT BY DEFAULT AND AT THE BOTTOM. These are not things somebody came here
   * to do, and one of them cannot be undone - so they are behind a deliberate
   * tap rather than sitting beside the controls that change geometry.
   */
  const [managing, setManaging] = useState(false);
  const [newName, setNewName] = useState('');
  /** Set once "remove" has been pressed: the second press is the one that acts. */
  const [confirmDelete, setConfirmDelete] = useState(false);

  /** A verdict taken just now, which replaces the stored one on screen. */
  const [rechecked, setRechecked] = useState<Checks | null>(null);
  /** The last thing a save did, said back. Cleared when the part changes. */
  const [saved, setSaved] = useState<string | null>(null);
  /**
   * This part's own schema, which is where the change words come from.
   *
   * Null for an imported mesh or an engine that cannot describe the template,
   * and then nothing is suggested - the box still takes any sentence. Offering
   * "make it wider" for a part with no width would be guessing at what it has.
   */
  const [schema, setSchema] = useState<TemplateInfo | null>(null);

  useEffect(() => {
    setShowing(name);
  }, [name]);

  useEffect(() => {
    let live = true;
    setGlb(null);
    setDetail(null);
    setProblem(null);
    setRechecked(null);
    setSaved(null);
    setPending({});
    setLayout('assembled');
    setManaging(false);
    setConfirmDelete(false);
    setNewName('');

    api
      .part(showing)
      .then((d) => live && setDetail(d))
      .catch((error) => live && setProblem(String(error?.message ?? error)));

    // A DRAFT HAS NO MESH, so asking for its GLB is a 404 that is not a fault.
    // The part payload says `has_stl`, but it has not arrived yet at this
    // point, so the failure is simply not reported as a problem - the draft
    // panel below explains the part instead.
    api
      .partGlb(showing)
      .then((bytes) => live && setGlb(bytes))
      .catch(() => undefined);

    return () => {
      live = false;
    };
  }, [api, showing]);

  // The build's own payload is richer than the library's, but only for the
  // part that was just built - an option is a different part and has to be
  // read off disk like any other.
  const fresh = built && (showing === built.dir || showing === built.name) ? built : undefined;

  // THE PART PAYLOAD HAS NO TOP-LEVEL `verdict` FIELD, and this used to read
  // one - `detail.verdict` was always undefined, and the stored verdict was
  // reached only because it came third in a fallback chain. The verdict lives
  // in `checks`, which is where the server puts it.
  const checks = rechecked ?? detail?.checks ?? null;
  const verdict = fresh?.verdict ?? checks?.verdict ?? '';
  const known = Boolean(verdict);
  const passed = fresh ? fresh.ok : (checks?.ok ?? false);

  const draft = detail?.draft ?? null;
  /**
   * SOMEBODY ELSE'S TRIANGLES, and the screen has to know.
   *
   * An import has no spec: there is nothing for a sentence to change and no
   * schema to hang sliders on. Offering either is offering a control that
   * cannot work - and this screen was offering both, plus a "change it" box
   * whose refine would fail on a part with no spec.yaml to refine.
   */
  const imported = detail?.origin === 'imported';
  const size = fresh?.size_mm ?? detail?.size_mm ?? null;
  const watertight = fresh?.watertight ?? detail?.watertight ?? null;
  const bodies = fresh?.bodies ?? detail?.bodies ?? null;
  const volume = fresh?.volume_cm3 ?? detail?.volume_cm3 ?? null;
  const material = fresh?.material ?? detail?.material ?? null;
  const template = fresh?.template ?? detail?.template ?? null;
  const files = detail?.files ?? fresh?.files ?? [];
  const reportMd = detail?.report_md ?? fresh?.report_md ?? '';

  const problems = fresh?.problems ?? checks?.problems ?? [];
  const warnings = fresh?.warnings ?? checks?.warnings ?? [];
  // BOTH SOURCES, BECAUSE ONLY ONE IS EVER PRESENT. A part just built carries
  // its assumptions in the build result; a part opened from the library has
  // them read back off run.json. They are the same list.
  const assumptions: Assumption[] = fresh?.assumptions ?? detail?.assumptions ?? [];
  const options: PartOption[] = fresh?.options ?? [];
  const shownName = fresh?.name ?? detail?.name ?? showing;
  // THE SPEC'S OWN PARAMS, so a choice already in force is not offered back.
  const params = ((detail?.spec as { params?: Record<string, unknown> } | undefined)?.params) ?? {};
  // WHERE THIS ONE SITS IN ITS OWN HISTORY. A refine writes a NEW part and
  // leaves the old one alone, which is what makes editing safe - and turned
  // four tweaks into four tiles all reading "birdhouse".
  const mine = (parts ?? []).find((p) => p.dir === showing);
  const chain = mine ? chainOf(parts ?? [], mine) : [];

  /**
   * The tab actually being shown.
   *
   * `tab` is what was last chosen and it survives moving between parts, so it
   * can be "change it" when the part in hand is an import that has no such
   * tab. Resolving it once here keeps every branch below reading as one
   * comparison instead of each re-deriving the fallback - the first attempt at
   * this put the correction inline and produced a condition nobody could read.
   */
  const at: Tab = imported && tab === 'change it' ? 'measured' : tab;

  const tweaks = tweaksFor(schema, params);

  // SLIDERS FOR A PART WITH NO TEMPLATE TOO.
  //
  // `dimensionsOf` reads a TEMPLATE's parameter schema, and this screen used
  // to stop there - no template, no schema, no controls, for most of what
  // whittle generates. An ops spec has no parameter names, so the server
  // sends its numbers addressed by position with the bounds off the op
  // models; see api.ServedDimension and dsl.op_dimensions.
  //
  // Both lists end up as the same `Dimension` and go through the same
  // rebuild, which posts the name straight back - "0.width_mm" is as good an
  // address as "wall_mm" and the params route takes either.
  const dimensions = template
    ? dimensionsOf(schema, params, assumptions.map((a) => a.name))
    : dimensionsFromOps(fresh?.dimensions ?? detail?.dimensions);

  // THE PART'S OWN SCHEMA, for the words it will understand. A failure here is
  // silent on purpose: no suggestions is a smaller screen, not a broken one,
  // and the change box works without it.
  useEffect(() => {
    let live = true;
    setSchema(null);
    if (!template) return undefined;
    api
      .templateInfo(template)
      .then((found) => live && setSchema(found))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [api, template]);


  /**
   * RULE 32, ON THE SCREEN. This is the way in for a change, not a menu of
   * parameters - "make this roof a triangular roof" is what a person types,
   * and the engine decides it against this part's own schema.
   */
  const change = useCallback(async () => {
    const text = instruction.trim();
    if (!text) return;
    setBusy(true);
    setProblem(null);
    try {
      const { job } = await api.refine(showing, text);
      setInstruction('');
      onChanging(job, text, 'refine');
    } catch (error: any) {
      setProblem(error instanceof ApiError ? error.message : String(error?.message ?? error));
    } finally {
      setBusy(false);
    }
  }, [api, instruction, onChanging, showing]);

  const edit = useCallback(async () => {
    setBusy(true);
    setProblem(null);
    try {
      onEdit(await api.projectFromPart(showing));
    } catch (error: any) {
      setProblem(error instanceof ApiError ? error.message : String(error?.message ?? error));
    } finally {
      setBusy(false);
    }
  }, [api, onEdit, showing]);

  /**
   * Check it again, now, against the profile as it stands today.
   *
   * CHEAP, WHICH IS WHY IT IS A BUTTON. Measured at 0.3s on a part whose build
   * took 151s - the expensive thing in a build is the model call, not the
   * checking. It writes nothing on the server: a re-check is a reading, and
   * overwriting run.json would destroy the record of what the part was given
   * when it was made.
   */
  /**
   * Build it again with the numbers as they have been dragged to.
   *
   * ONE REQUEST FOR EVERY CHANGE, and it goes through the same screen a first
   * generate does - same log, same rig, same checks at the end. A part whose
   * numbers were set is not a lesser part and does not get a lesser path.
   */
  const rebuild = useCallback(async () => {
    const moved = Object.keys(pending);
    if (!moved.length) return;
    setBusy(true);
    setProblem(null);
    try {
      const { job } = await api.setParams(showing, pending);
      setPending({});
      onChanging(
        job,
        // THE LABEL, NOT THE ADDRESS. A template parameter reads well with
        // its suffix trimmed - "wall 3.5". An ops number is addressed by
        // position, and "0.width 90" on the screen that shows what is being
        // built is not something anybody asked for. The dimension already
        // carries the readable name.
        moved
          .map((k) => {
            const named = dimensions.find((d) => d.name === k);
            return `${named?.label ?? k.replace(/_mm$|_deg$/, '')} ${pending[k]}`;
          })
          .join(', '),
        'params',
      );
    } catch (error: any) {
      setProblem(error instanceof ApiError ? error.message : String(error?.message ?? error));
    } finally {
      setBusy(false);
    }
  }, [api, dimensions, onChanging, pending, showing]);

  const removeIt = useCallback(async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.deletePart(showing);
      onDeleted();
    } catch (error: any) {
      setProblem(error instanceof ApiError ? error.message : String(error?.message ?? error));
      setConfirmDelete(false);
    } finally {
      setBusy(false);
    }
  }, [api, onDeleted, showing]);

  const renameIt = useCallback(async () => {
    const wanted = newName.trim();
    if (!wanted) return;
    setBusy(true);
    setProblem(null);
    try {
      const { dir } = await api.renamePart(showing, wanted);
      setNewName('');
      setManaging(false);
      // THE DIRECTORY IS THE IDENTITY, so the screen has to follow it - staying
      // on the old name would be showing a part that no longer answers to it.
      onRenamed(dir);
    } catch (error: any) {
      setProblem(error instanceof ApiError ? error.message : String(error?.message ?? error));
    } finally {
      setBusy(false);
    }
  }, [api, newName, onRenamed, showing]);

  const recheck = useCallback(async () => {
    setBusy(true);
    setProblem(null);
    try {
      const { checks: now } = await api.verify(showing);
      setRechecked(now);
      setTab('checks');
    } catch (error: any) {
      setProblem(error instanceof ApiError ? error.message : String(error?.message ?? error));
    } finally {
      setBusy(false);
    }
  }, [api, showing]);

  const save = useCallback(
    async (ext: string) => {
      setBusy(true);
      setProblem(null);
      setSaved(null);
      const result = await saveToFolder(
        api.partFileUrl(showing, ext),
        saveName(shownName, ext),
        SAVEABLE[ext] ?? 'application/octet-stream',
      );
      setBusy(false);
      if (result.ok) {
        setSaved(`${saveName(shownName, ext)} saved to ${result.where}`);
      } else if (!result.cancelled) {
        setProblem(result.message);
      }
    },
    [api, shownName, showing],
  );

  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Header
        back={onClose}
        backLabel="back"
        title={shownName}
        subtitle={subtitle(showing, shownName, fresh)}
        right={busy ? <Rig size={40} /> : undefined}
      />

      {/* A DRAFT HAS NOTHING TO DRAW. Showing an empty canvas over "fetching
          the geometry…" for ever is what this screen used to do to a part that
          never built, and it reads as a broken viewer rather than as a build
          that did not finish. */}
      {draft ? null : (
        <View style={styles.viewport}>
          {layout === 'assembled' ? (
            <Viewport glb={glb} placeholder="fetching the geometry…" />
          ) : (
            // THE PRINT LAYOUT IS A RENDER, NOT THE GLB. The GLB route serves
            // the assembled mesh and only that; the print layout is the STL on
            // disk, and the server already renders and caches a turntable of
            // it. Asking for one cached PNG beats shipping a second mesh down
            // the wire to look at it once.
            <View style={styles.bed}>
              <Image
                source={{ uri: api.frameUrl(showing, 3, 900, 'print') }}
                style={styles.bedImage}
                resizeMode="contain"
              />
            </View>
          )}
        </View>
      )}

      {/* WHICH WAY UP, and it is not a display preference. A birdhouse is a
          box with its roof panels lying flat beside it, because that is how it
          prints without support - and the app only ever showed the assembled
          form, so somebody could look at a finished-looking birdhouse and have
          no idea it comes off the bed in three pieces. */}
      {/* ONLY WHEN WE KNOW THERE IS AN STL. `has_stl !== false` was true
          while the payload was still in flight, so the toggle appeared, was
          tapped, and drew a 404 as an empty box. The print layout IS the STL
          on disk - no STL, no print layout to show. */}
      {!draft && detail?.has_stl === true ? (
        <View style={styles.layoutRow}>
          <Segmented
            options={LAYOUTS}
            value={layout === 'assembled' ? 'assembled' : 'on the bed'}
            onChange={(next) => setLayout(next === 'assembled' ? 'assembled' : 'print')}
            style={styles.grow}
          />
          {bodies !== null && bodies > 1 ? (
            <Mono size="micro" color={core.dim}>
              {bodies} pieces
            </Mono>
          ) : null}
        </View>
      ) : null}

      <Surface step="pill" style={styles.verdictBar}>
        <Verdict
          state={draft ? 'fail' : !known ? 'waiting' : passed ? 'pass' : 'fail'}
          text={
            draft
              ? 'this one never built'
              : known
                ? verdict
                : 'no verdict recorded for this part - check it now'
          }
        />
        {/* WHEN IT WAS CHECKED, AND WHETHER THE GROUND HAS MOVED. A verdict
            measured against a 0.4 mm nozzle says nothing certain about a
            machine now running 0.6, and the server works that out rather than
            leaving it to be noticed. */}
        {checks?.drift?.length ? (
          <View style={styles.drift}>
            {checks.drift.map((line, index) => (
              <Verdict key={index} state="warn" text={line} />
            ))}
          </View>
        ) : null}
      </Surface>

      {!draft ? (
        <Segmented options={imported ? IMPORT_TABS : TABS} value={at} onChange={setTab} />
      ) : null}

      <ScrollView
        style={styles.sheet}
        contentContainerStyle={styles.sheetBody}
        keyboardShouldPersistTaps="handled">
        {problem ? <Problem text={problem} /> : null}
        {saved ? (
          <Surface step="well" style={styles.saved}>
            <Verdict state="pass" text={saved} />
          </Surface>
        ) : null}

        {draft ? <DraftPanel draft={draft} /> : null}

        {chain.length > 1 ? (
          <Chain chain={chain} showing={showing} onShow={onShowPart} />
        ) : null}

        {imported ? <Imported detail={detail!} onEdit={edit} busy={busy} /> : null}

        {!draft && !imported && at === 'change it' ? (
          <ChangeTab
            assumptions={assumptions}
            tweaks={tweaks}
            dimensions={dimensions}
            pending={pending}
            onDrag={(name, value) => setPending((p) => ({ ...p, [name]: value }))}
            onRebuild={rebuild}
            hasSchema={Boolean(schema)}
            onSay={setInstruction}
            onSliders={edit}
            busy={busy}
          />
        ) : null}

        {!draft && at === 'checks' ? (
          <ChecksTab
            checks={checks}
            problems={problems}
            warnings={warnings}
            onRecheck={recheck}
            busy={busy}
            api={api}
            showing={showing}
            hasMesh={detail?.has_stl ?? Boolean(glb)}
          />
        ) : null}

        {!draft && at === 'measured' ? (
          <MeasuredTab
            size={size}
            volume={volume}
            bodies={bodies}
            material={material}
            template={template}
            watertight={watertight}
            level={fresh?.level ?? detail?.level ?? null}
            options={options}
            showing={showing}
            onShow={setShowing}
          />
        ) : null}

        {!draft && at === 'report' ? (
          <ReportTab markdown={reportMd} />
        ) : null}

        {/* MANAGING THE PART ITSELF, last and shut. Renaming is how
            "birdhouse_6" becomes something a person chose; removing is how a
            library of timed-out drafts stops burying the good ones. */}
        <Panel title="this part">
          <Quiet
            label={managing ? '– done' : 'rename or remove'}
            onPress={() => {
              setManaging((m) => !m);
              setConfirmDelete(false);
            }}
          />
          {managing ? (
            <>
              <Mono size="micro" color={core.dim}>
                its folder is {showing}
              </Mono>
              <View style={styles.renameRow}>
                <Surface step="well" style={styles.renameWell}>
                  <TextInput
                    value={newName}
                    onChangeText={setNewName}
                    placeholder="a name you will recognise"
                    placeholderTextColor={core.dim}
                    autoCapitalize="none"
                    autoCorrect={false}
                    style={styles.input}
                  />
                </Surface>
                <Button
                  label="rename"
                  onPress={renameIt}
                  disabled={busy || !newName.trim()}
                />
              </View>
              <Prose size="body" color={core.dim}>
                This renames the folder, which is what the app navigates by. What the part calls
                itself inside its own spec is left alone.
              </Prose>

              {/* TWO PRESSES, AND THE SECOND ONE SAYS WHAT IT DOES. A single
                  "delete" next to a "rename" is a mistap away from losing work
                  that took twenty minutes to build. */}
              {confirmDelete ? (
                <>
                  <Verdict
                    state="fail"
                    text={`remove ${showing} and everything in it? This cannot be undone.`}
                  />
                  <View style={styles.actions}>
                    <Button label="yes, remove it" primary onPress={removeIt} disabled={busy} />
                    <Quiet label="keep it" onPress={() => setConfirmDelete(false)} />
                  </View>
                </>
              ) : (
                <Quiet
                  label="remove this part"
                  color={pen.fail}
                  onPress={() => setConfirmDelete(true)}
                />
              )}
            </>
          ) : null}
        </Panel>

        {/* TAKE IT AWAY. Only the formats that are actually on disk: the
            server's file route is an allow-list and offering a format it does
            not have is offering a download that fails. */}
        {files.length ? (
          <Panel title="save it">
            <Prose size="body" color={core.dim}>
              Pick a folder on the phone and the file is written there, where a slicer can open
              it.
            </Prose>
            {files.map((ext) => (
              <View key={ext} style={styles.saveRow}>
                <View style={styles.grow}>
                  <Mono size="label" weight="medium">
                    {ext.toUpperCase()}
                  </Mono>
                  {FORMAT_NOTE[ext] ? (
                    <Mono size="micro" color={core.dim}>
                      {FORMAT_NOTE[ext]}
                    </Mono>
                  ) : null}
                </View>
                <Button
                  label="save"
                  primary={ext === 'stl'}
                  onPress={() => save(ext)}
                  disabled={busy}
                />
              </View>
            ))}
          </Panel>
        ) : null}
      </ScrollView>

      {/* WHAT HAS MOVED AND NOT BEEN BUILT, above the box rather than inside
          the scrolling sheet - a person who drags three sliders and scrolls
          away has no other way to find the button, and an unbuilt change that
          is out of sight is a change they will believe happened. */}
      {Object.keys(pending).length ? (
        <Surface step="pill" style={styles.pendingBar}>
          <View style={styles.grow}>
            <Mono size="label" weight="medium" color={core.phosphor}>
              {Object.keys(pending).length} change
              {Object.keys(pending).length === 1 ? '' : 's'} not built yet
            </Mono>
            <Mono size="micro" color={core.dim} numberOfLines={1}>
              {Object.entries(pending)
                .map(([name, value]) => `${name.replace(/_mm$|_deg$/, '')} ${value}`)
                .join('  ·  ')}
            </Mono>
          </View>
          <Quiet label="undo" onPress={() => setPending({})} />
          <Button label="build it" primary onPress={rebuild} disabled={busy} />
        </Surface>
      ) : null}

      {/* SAY WHAT TO CHANGE. Not a parameter list - the sentence goes to the
          engine, which reads it against this part's own template. A draft can
          be changed too: the request is on disk and refining it is the way
          out of a failed build.

          NOT FOR AN IMPORT. There is no spec to read the sentence against, so
          /api/refine answers "no part called x, or it has no spec.yaml to
          change" - a box that always fails, on the most prominent line of the
          screen. Its mesh editor is one tap away instead. */}
      {!imported ? (
      <Surface step="pill" style={styles.command}>
        <TextInput
          value={instruction}
          onChangeText={setInstruction}
          onSubmitEditing={change}
          returnKeyType="send"
          placeholder={
            // THE PLACEHOLDER IS ABOUT THIS PART, not about a birdhouse. It
            // read "make this roof a triangular roof" on every part in the
            // library - on a keyring tag, which has no roof, that is an
            // example of something the engine will refuse, offered as the
            // example of what to type. The first suggestion this part's own
            // schema produced is the honest one; a part with no schema gets a
            // shape-free prompt rather than a borrowed one.
            tweaks[0]?.say ?? 'say what to change'
          }
          placeholderTextColor={core.dim}
          style={styles.input}
        />
        <Button label="change it" primary onPress={change} disabled={!instruction.trim() || busy} />
      </Surface>
      ) : null}

      {!draft ? (
        <View style={styles.footer}>
          {/* AN IMPORT ALREADY HAS THIS AS ITS PRIMARY ACTION, up in the panel
              that explains what it is - a second copy down here would be two
              buttons doing the same thing on one screen. */}
          {!imported ? (
            <Button label="sliders" onPress={edit} disabled={busy} style={styles.footerButton} />
          ) : null}
          <Button label="check again" onPress={recheck} disabled={busy} style={styles.footerButton} />
        </View>
      ) : null}
    </KeyboardAvoidingView>
  );
}

/** What goes under the title: the directory, and how the build went. */
function subtitle(showing: string, shownName: string, fresh?: BuiltPart): string | undefined {
  const bits: string[] = [];
  // The directory, when it is not the same as the name - so it is always
  // possible to tell two refinements of one part apart.
  if (showing !== shownName) bits.push(showing);
  if (fresh?.elapsed_s !== undefined) {
    const tries = fresh.attempts ?? 1;
    bits.push(`built in ${fresh.elapsed_s}s over ${tries} attempt${tries === 1 ? '' : 's'}`);
  }
  return bits.length ? bits.join(' · ') : undefined;
}

/**
 * A mesh somebody brought in, and what can honestly be done to it.
 *
 * THIS SCREEN WAS OFFERING IT THE WRONG TOOLS. An import has no spec.yaml, so
 * "make it taller" has no parametric model to change and the dimension sliders
 * have no schema to take their bounds from - and the screen offered both, plus
 * a change box whose refine would fail on a part with nothing to refine. The
 * `origin` flag existed to prevent exactly this and was not being read here.
 *
 * WHAT IT DOES HAVE IS A MESH, which is not a lesser thing: every check runs
 * on it, every measurement is real, it exports, and the whole mesh editor
 * applies - hollow it, cut it to fit the bed, flatten its base, scale it. That
 * is the honest offer and it leads.
 */
function Imported({
  detail,
  onEdit,
  busy,
}: {
  detail: PartDetail;
  onEdit: () => void;
  busy: boolean;
}) {
  return (
    <>
      <Panel title="brought in">
        {detail.source_name ? (
          <Row label="the file" value={detail.source_name} />
        ) : null}
        {detail.triangles !== undefined ? (
          <Row label="triangles" value={detail.triangles.toLocaleString()} />
        ) : null}
        {detail.note ? (
          <Prose size="body" color={core.dim}>
            {detail.note}
          </Prose>
        ) : null}
      </Panel>

      <Panel title="what you can do with it">
        <Prose size="body" color={core.dim}>
          This is a mesh rather than a design, so it has no dimensions to type at - what it has
          is every operation that works on any model: hollow it, cut it to fit the bed, flatten
          its base so it stands, scale it, clean up stray shells.
        </Prose>
        <Button label="open the mesh" primary onPress={onEdit} disabled={busy} />
      </Panel>

      {detail.fit_note ? (
        <Panel title="why it has no sliders">
          {/* THE IMPORTER'S OWN REASONING, which it worked out at ingest and
              which was being discarded. "cross-sections vary by 52.7% around
              the axis, so this is not a turned shape - fitting a bowl to it
              would produce a confident wrong answer" is a better answer than
              any apology this screen could write, and it is the difference
              between a limitation and a refusal somebody can trust. */}
          <Prose size="body" color={core.dim}>
            {detail.fit_note}
          </Prose>
        </Panel>
      ) : null}
    </>
  );
}

/**
 * Every build of this part, and which one you are looking at.
 *
 * A REFINE WRITES A NEW PART AND KEEPS THE OLD ONE. That is deliberate - the
 * last good result is never destroyed by the next change - and it means the
 * ordinary workflow produces a chain: say "a birdhouse", change the roof, make
 * it taller, set the wall to 3.5, and there are four verified parts on disk.
 *
 * The library was drawing them as four tiles all reading "birdhouse", and the
 * only way to tell which was which was to open each one. This is the history
 * that was already on disk, said out loud.
 *
 * NOT CALLED "v1, v2". There is no stored version number and inventing one
 * implies the engine keeps it. The figure shown is the number the allocator
 * put on the directory, which is in the directory name anyway.
 */
function Chain({
  chain,
  showing,
  onShow,
}: {
  chain: LibraryPart[];
  showing: string;
  onShow: (dir: string) => void;
}) {
  const at = chain.findIndex((p) => p.dir === showing);

  return (
    <Panel title={`build ${at + 1} of ${chain.length}`}>
      <Prose size="body" color={core.dim}>
        Every change built a new part and left the one before it alone. Tap any of them to open
        it.
      </Prose>
      <View style={styles.chain}>
        {chain.map((entry) => {
          const here = entry.dir === showing;
          return (
            <Pressable key={entry.dir} onPress={() => onShow(entry.dir)} disabled={here}>
              <Surface
                step="well"
                style={[styles.chainItem, here && { borderColor: core.phosphor }]}>
                <Mono
                  size="label"
                  weight={here ? 'medium' : 'regular'}
                  color={here ? core.phosphor : core.screen}>
                  {buildNumber(entry.dir)}
                </Mono>
                {/* A BUILD THAT FAILED IS STILL PART OF THE HISTORY, and is
                    the one somebody is most likely to want back. */}
                {!entry.built ? (
                  <Mono size="micro" color={pen.warn}>
                    no mesh
                  </Mono>
                ) : null}
              </Surface>
            </Pressable>
          );
        })}
      </View>
      {/* The size of each, so the chain is readable as a change rather than as
          a row of numbers. */}
      {chain.some((entry) => entry.size_mm) ? (
        <View style={styles.chainSizes}>
          {chain.map((entry) => (
            <Mono
              key={entry.dir}
              size="micro"
              color={entry.dir === showing ? core.screen : core.dim}
              numberOfLines={1}>
              {buildNumber(entry.dir)} · {
                entry.size_mm
                  ? `${entry.size_mm.map((v) => Math.round(v)).join(' × ')} mm`
                  : 'never built'
              }
            </Mono>
          ))}
        </View>
      ) : null}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// changing it, which is what this screen is for
// ---------------------------------------------------------------------------

/**
 * The second half of the product, and until now the missing half.
 *
 * THE WORKFLOW THIS SERVES. Somebody types "a bracket". They do not type
 * dimensions, because people describe things rather than specify them. The
 * engine builds a good one and marks every number it had to choose. Then the
 * part gets changed until it is right - by saying so, or with sliders - and
 * that loop is the product as much as the first build is.
 *
 * WHAT THIS SCREEN USED TO OFFER FOR IT: one empty text field at the bottom,
 * under a verdict and three tabs of numbers, with a placeholder about a roof.
 * An empty box labelled "say what to change" fails the same way an empty box
 * labelled "describe a part" fails - it works for somebody who already knows
 * what the parser accepts.
 *
 * SO THERE ARE TWO WAYS IN, BOTH VISIBLE.
 *
 *   the assumptions   every number nobody asked for, named, with the reason it
 *                     was chosen. Tapping one writes the sentence that changes
 *                     it. This is the list a two-word request produces, and it
 *                     is the honest answer to "what can I change".
 *
 *   the words         "make it taller", "make the roof gable" - taken from the
 *                     parser's own vocabulary and filtered to what THIS part
 *                     has, so nothing offered here can be declined.
 *
 * And the sliders, for when the sentence is not the tool - an exact number, or
 * a parameter with no English word for it yet.
 */
function ChangeTab({
  assumptions,
  tweaks,
  dimensions,
  pending,
  onDrag,
  onRebuild,
  hasSchema,
  onSay,
  onSliders,
  busy,
}: {
  assumptions: Assumption[];
  tweaks: Tweak[];
  dimensions: Dimension[];
  pending: Record<string, number>;
  onDrag: (name: string, value: number) => void;
  onRebuild: () => void;
  hasSchema: boolean;
  onSay: (sentence: string) => void;
  onSliders: () => void;
  busy: boolean;
}) {
  return (
    <>
      {tweaks.length ? (
        <Panel title="say it in the box below">
          <Prose size="body" color={core.dim}>
            Tap one to put it in the box, edit it if you like, then send it. These are the words
            this part understands - it takes any sentence, these are just the common ones.
          </Prose>
          <View style={styles.tweaks}>
            {tweaks.map((tweak) => (
              <Chip key={tweak.say} label={tweak.say} onPress={() => onSay(tweak.say)} />
            ))}
          </View>
        </Panel>
      ) : null}

      {assumptions.length ? (
        <Panel title="what it chose for you">
          {/* RULE 14. A dimension that could not be measured becomes a named
              parameter marked ASSUMPTION, under a heading that says so rather
              than blending into the measurements. For a two-word request that
              is EVERY number in the part, which makes this the most useful
              panel on the screen rather than a footnote. */}
          <Prose size="body" color={core.dim}>
            You did not say, so it decided - and said why. Tap one to change it.
          </Prose>
          {assumptions.map((assumption) => (
            <AssumptionRow
              key={assumption.name}
              assumption={assumption}
              onSay={onSay}
            />
          ))}
        </Panel>
      ) : null}

      {dimensions.length ? (
        <Panel title="its own numbers">
          {/* THE SENTENCE HAS TO BE TRUE OF THESE SLIDERS.
              For a template part the ends ARE the schema's bounds. For a part
              built from operations they are not: the schema accepts anything
              up to 1000 mm and a slider spanning that cannot pick 8.00, so
              the ends are scaled off the value the number holds and the real
              limit is enforced at build time. Saying "the template's own
              limits" over the second kind would be a claim about where a
              control stops that is simply wrong. */}
          <Prose size="body" color={core.dim}>
            {hasSchema
              ? "Drag as many as you like, then build it once. The ends are the template's own limits, not a guess - it will not let you ask for something it cannot make."
              : 'Drag as many as you like, then build it once. The ends are around what each number holds now, so there is something to aim with; ask for more than the engine allows and it will say so rather than build it.'}
          </Prose>
          {dimensions.map((dimension) => (
            <DimensionSlider
              key={dimension.name}
              dimension={dimension}
              pending={pending[dimension.name]}
              onDrag={(value) => onDrag(dimension.name, value)}
              disabled={busy}
            />
          ))}
        </Panel>
      ) : null}

      <Panel title="or work on the mesh">
        {/* THE HONEST DESCRIPTION, and it used to be wrong here. This does not
            open "every step of its build" - it opens the part's MESH, with the
            operations that work on triangles: hollow it, cut it to fit the
            bed, fillet an edge. The part's own dimensions are the sliders
            above, which rebuild from the spec. Both are useful and they are
            not the same thing. */}
        <Prose size="body" color={core.dim}>
          Opens the finished mesh with the operations that work on any model - hollow it, cut it
          to fit the bed. For the part's own dimensions, use the sliders above.
        </Prose>
        <Button label="open the mesh" onPress={onSliders} disabled={busy} />
      </Panel>

      {!assumptions.length && !tweaks.length && !dimensions.length ? (
        <Panel>
          {/* NOT A DEAD END. The box below still takes any sentence; what is
              missing is the machine's description of this part, which is what
              the suggestions are built from. Saying which is missing is the
              difference between "nothing to do here" and "type it yourself". */}
          <Empty
            title={
              hasSchema
                ? 'nothing was assumed for this one'
                : 'this part has no template behind it'
            }
            hint="The box below still takes any sentence - what is missing is only the list of suggestions."
          />
        </Panel>
      ) : null}
    </>
  );
}


/**
 * One of the part's own numbers, as something to drag.
 *
 * THE ENDS ARE THE TEMPLATE'S, WRITTEN DOWN. `wall_mm` is `gt=0.4, le=30.0`
 * because that is what the template accepts, and showing where it stops is
 * what turns a control that mysteriously will not move into one whose limits
 * are part of the answer.
 *
 * NOTHING IS SENT WHILE THE FINGER IS DOWN. Unlike the mesh editor - where the
 * server rebuilds one step from a cache in 43 ms - moving one of these means
 * recompiling the part and running every check. So the value is held locally,
 * shown as pending, and built when the person says so.
 */
function DimensionSlider({
  dimension,
  pending,
  onDrag,
  disabled,
}: {
  dimension: Dimension;
  pending: number | undefined;
  onDrag: (value: number) => void;
  disabled: boolean;
}) {
  const shown = pending ?? dimension.value;
  const moved = pending !== undefined && pending !== dimension.value;

  return (
    <View style={styles.dimension}>
      <View style={styles.dimensionHead}>
        <Mono size="label" color={core.dim} style={styles.grow} numberOfLines={1}>
          {dimension.label}
          {/* WHICH ONES THE ENGINE CHOSE, marked where a person is deciding
              what to move. For a two-word request that is most of them, and
              they are the ones worth looking at first. */}
          {dimension.assumed ? '  ·  it chose this' : ''}
        </Mono>
        <Mono size="label" weight="medium" color={moved ? core.phosphor : core.screen}>
          {trimNumber(shown)}
          {dimension.units ? ` ${dimension.units}` : ''}
        </Mono>
      </View>

      <Slider
        disabled={disabled}
        minimumValue={dimension.low}
        maximumValue={dimension.high}
        value={dimension.value}
        step={dimension.whole ? 1 : 0}
        minimumTrackTintColor={core.phosphor}
        maximumTrackTintColor={core.etch}
        thumbTintColor={core.phosphor}
        onSlidingComplete={(value) =>
          // ROUNDED TO SOMETHING A PERSON WOULD SAY. A slider hands back
          // 149.83726, and a part built to that is a part whose spec nobody
          // can read - two decimals for a length, whole numbers for a count.
          onDrag(dimension.whole ? Math.round(value) : Number(value.toFixed(2)))
        }
      />

      <View style={styles.bounds}>
        <Mono size="micro" color={core.dim}>
          {trimNumber(dimension.low)}
        </Mono>
        {moved ? (
          <Mono size="micro" color={core.phosphor}>
            was {trimNumber(dimension.value)}
          </Mono>
        ) : null}
        <Mono size="micro" color={core.dim}>
          {trimNumber(dimension.high)}
        </Mono>
      </View>

      {dimension.description ? (
        <Prose size="body" color={core.dim}>
          {dimension.description}
        </Prose>
      ) : null}
    </View>
  );
}

/** A number as a person would write it, without inventing precision. */
function trimNumber(value: number): string {
  return String(Number(value.toFixed(2)));
}

/**
 * One assumed number, and the one-tap way to change it.
 *
 * THE SENTENCE IS ENGLISH, NOT THE FIELD NAME. `height_mm` becomes "make it
 * 200mm tall", because rule 32 puts the parameter on the implementation side
 * and the English on the interface side - and because that is the phrasing the
 * parser actually reads.
 *
 * An assumption with no such phrasing still shows its value and its reason and
 * simply does not offer the tap. Inventing "set corner_r_mm to 6" would be a
 * suggestion that fails, and a failing suggestion teaches people not to trust
 * the ones that work.
 */
function AssumptionRow({
  assumption,
  onSay,
}: {
  assumption: Assumption;
  onSay: (sentence: string) => void;
}) {
  const say = sayForAssumption(assumption.name, assumption.value, assumption.units);
  const shown = `${assumption.value}${assumption.units ? ` ${assumption.units}` : ''}`;

  const body = (
    <Surface step="well" style={styles.assumption}>
      <View style={styles.assumptionHead}>
        <Mono size="label" weight="medium" style={styles.grow} numberOfLines={1}>
          {assumption.name.replace(/_mm$/, '').replace(/_/g, ' ')}
        </Mono>
        <Mono size="label" weight="medium" color={pen.warn}>
          {shown}
        </Mono>
      </View>
      <Prose size="body" color={core.dim}>
        {assumption.why}
      </Prose>
      {say ? (
        <Mono size="micro" color={core.phosphor}>
          tap to say “{say}”
        </Mono>
      ) : null}
    </Surface>
  );

  return say ? <Pressable onPress={() => onSay(say)}>{body}</Pressable> : body;
}

// ---------------------------------------------------------------------------
// whether it prints
// ---------------------------------------------------------------------------

/**
 * Every check the engine ran, as a measured value and a status.
 *
 * A LINE IS A NUMBER AND A STATUS, never a status alone. "watertight yes" and
 * "worst overhang 12.4 deg from vertical" are what make this a report rather
 * than a green tick, and brief 6.7 forbids colour carrying meaning on its own
 * anyway. The server builds these lines - `_checks_from_report` - so the
 * browser and the phone cannot come to disagree about what a check is called.
 */
function ChecksTab({
  checks,
  problems,
  warnings,
  onRecheck,
  busy,
  api,
  showing,
  hasMesh,
}: {
  checks: Checks | null;
  problems: string[];
  warnings: string[];
  onRecheck: () => void;
  busy: boolean;
  api: Api;
  showing: string;
  hasMesh: boolean;
}) {
  if (!checks) {
    return (
      <Panel>
        <Empty
          title="no verdict on file"
          hint="This part predates the machine recording verdicts, or it was imported rather than generated. Checking it now takes about a second."
        />
        <Button label="check it now" primary onPress={onRecheck} disabled={busy} />
      </Panel>
    );
  }

  const failed = checks.lines.filter((line) => line.status === 'fail');
  const warned = checks.lines.filter((line) => line.status === 'warn');
  const rest = checks.lines.filter((line) => line.status === 'pass' || line.status === 'info');

  return (
    <>
      {problems.length ? (
        <Panel title="what stops it printing">
          {problems.map((text, index) => (
            <Verdict key={index} state="fail" text={text} />
          ))}
        </Panel>
      ) : null}

      {warnings.length ? (
        <Panel title="worth knowing">
          {warnings.map((text, index) => (
            <Verdict key={index} state="warn" text={text} />
          ))}
        </Panel>
      ) : null}

      <Panel title={checks.source === 'stored' ? 'checked when it was built' : 'checked just now'}>
        <Row label="against" value={describeProfile(checks)} />
        {/* Failures first, then warnings, then everything that passed. Thirty
            lines in file order buries the two that matter. */}
        {[...failed, ...warned, ...rest].map((line, index) => (
          <CheckRow key={`${line.name}-${index}`} line={line} />
        ))}
      </Panel>

      {hasMesh ? <Renders api={api} showing={showing} /> : null}
    </>
  );
}

/**
 * The two pictures that show what the numbers cannot.
 *
 * RULE 27, WHICH HAD NOWHERE TO BE KEPT: "The height map is the primary
 * geometry-verification visual, not the shaded render. A flat-shaded renderer
 * cannot show a recess whose floor shares a normal with the surrounding face."
 * Rule 28 goes further - no part is done until a height map has been generated
 * AND LOOKED AT - and until now there was nowhere in either client to look.
 *
 * On the checks tab rather than beside the 3D view, because that is what they
 * are: evidence. The viewport above is for turning a part around; these are
 * for seeing whether the floor is where it should be.
 */
function Renders({ api, showing }: { api: Api; showing: string }) {
  const [broken, setBroken] = useState<Record<string, boolean>>({});
  const mark = (kind: string) => () => setBroken((b) => ({ ...b, [kind]: true }));

  const sheets: { kind: 'heightmap' | 'section'; title: string; note: string }[] = [
    {
      kind: 'heightmap',
      title: 'height map',
      note: 'Every surface coloured by how high it stands, looking down the print direction. A recess whose floor faces the same way as everything around it is invisible in a shaded render and obvious here.',
    },
    {
      kind: 'section',
      title: 'section',
      note: 'Cut through the middle. This is where a wall that is thinner than it looks, or a cavity that did not close, shows up.',
    },
  ];

  const shown = sheets.filter((sheet) => !broken[sheet.kind]);
  if (!shown.length) return null;

  return (
    <Panel title="look at it">
      {shown.map((sheet) => (
        <View key={sheet.kind} style={styles.render}>
          <Mono size="label" weight="medium">
            {sheet.title}
          </Mono>
          {/* A PART BUILT BEFORE THESE WERE WRITTEN GENUINELY HAS NONE, and
              the route says so with a 404 rather than an empty image. React
              Native draws a 404 as a blank box, which looks like a broken app
              rather than an older part - so a failed load removes the panel
              instead of leaving a hole in it. */}
          <Image
            source={{ uri: api.renderUrl(showing, sheet.kind) }}
            style={styles.renderImage}
            resizeMode="contain"
            onError={mark(sheet.kind)}
          />
          <Prose size="body" color={core.dim}>
            {sheet.note}
          </Prose>
        </View>
      ))}
    </Panel>
  );
}

/** The nozzle and material a verdict was measured against, or silence. */
function describeProfile(checks: Checks): string {
  const bits: string[] = [];
  if (checks.nozzle_mm !== null && checks.nozzle_mm !== undefined) {
    bits.push(`${checks.nozzle_mm} mm nozzle`);
  }
  if (checks.material) bits.push(checks.material);
  if (checks.print_axis) bits.push(`printed along ${checks.print_axis}`);
  return bits.length ? bits.join(' · ') : 'not recorded';
}

/**
 * One check: its name, its measured value, and a status word.
 *
 * The status is a word and a pen, never a pen alone - the same rule Verdict
 * keeps, applied to a dense row where a coloured dot would have been the
 * tempting shortcut.
 */
function CheckRow({ line }: { line: CheckLine }) {
  const colours = {
    pass: pen.pass,
    warn: pen.warn,
    fail: pen.fail,
    info: core.dim,
  } as const;
  const words = { pass: 'ok', warn: 'watch', fail: 'no', info: '' } as const;

  return (
    <View style={styles.checkRow}>
      <Mono size="label" color={core.dim} style={styles.grow} numberOfLines={1}>
        {line.name}
      </Mono>
      <Mono size="label" weight="medium" color={colours[line.status]}>
        {line.value}
      </Mono>
      {words[line.status] ? (
        <Mono size="micro" color={colours[line.status]} style={styles.checkWord}>
          {words[line.status]}
        </Mono>
      ) : (
        <View style={styles.checkWord} />
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// what it is
// ---------------------------------------------------------------------------

function MeasuredTab({
  size,
  volume,
  bodies,
  material,
  template,
  watertight,
  level,
  options,
  showing,
  onShow,
}: {
  size: number[] | null;
  volume: number | null;
  bodies: number | null;
  material: string | null;
  template: string | null;
  watertight: boolean | null;
  level: number | null;
  options: PartOption[];
  showing: string;
  onShow: (name: string) => void;
}) {
  return (
    <>
      <Panel title="measured">
        {size ? <Row label="size" value={`${size.join(' × ')} mm`} /> : null}
        {volume !== null ? <Row label="volume" value={`${volume} cm³`} /> : null}
        {/* PIECES, not a guess. For anything with a moving part this is the
            fact that decides whether it works: two bodies turn, one body is
            fused solid. */}
        {bodies !== null ? <Row label="pieces" value={String(bodies)} /> : null}
        {watertight !== null ? (
          <Row
            label="watertight"
            value={watertight ? 'yes' : 'no'}
            valueColor={watertight ? pen.pass : pen.fail}
          />
        ) : null}
        {material ? <Row label="material" value={material} /> : null}
        {template ? <Row label="template" value={template} /> : null}
        {/* LEVEL 3 IS RAW CADQUERY AND IT IS MARKED. Rule 12: it is off by
            default, capped at one attempt, and anything it produces is REVIEW
            REQUIRED - which is a thing to say on the part, not only in a log
            nobody reopens. */}
        {level !== null ? (
          <Row
            label="built at level"
            value={level === 3 ? '3 - REVIEW REQUIRED' : String(level)}
            valueColor={level === 3 ? pen.warn : core.screen}
          />
        ) : null}
      </Panel>

      {options.length > 1 ? (
        <Panel title="other ways it could have gone">
          <Prose size="body" color={core.dim}>
            Built by walking the spec's own axes, so they cost seconds rather than another trip
            through the model.
          </Prose>
          {options.map((option) => (
            <Pressable key={option.name} onPress={() => onShow(option.name)}>
              <Surface
                step="well"
                style={[styles.option, option.name === showing && { borderColor: core.phosphor }]}>
                <Row label={option.label} value={option.verdict} />
                {option.envelope_mm ? (
                  <Mono size="micro" color={core.dim}>
                    {option.envelope_mm.map((v) => v.toFixed(1)).join(' × ')} mm
                  </Mono>
                ) : null}
              </Surface>
            </Pressable>
          ))}
        </Panel>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// the report
// ---------------------------------------------------------------------------

/**
 * The written report, set as monospace rather than prose.
 *
 * It is markdown with tables of numbers in it, and a proportional face turns
 * an aligned column of dimensions into a ragged one. No renderer: adding a
 * markdown library to draw one document would be a dependency for a screen,
 * and the report is written to be read as plain text - it is the file the
 * engine leaves in the part's own directory.
 */
function ReportTab({ markdown }: { markdown: string }) {
  if (!markdown) {
    return (
      <Panel>
        <Empty
          title="no written report"
          hint="Parts built through the pipeline leave one in their directory. An imported mesh has none."
        />
      </Panel>
    );
  }
  return (
    <Panel title="the report">
      <Mono size="micro" color={core.screen} style={styles.report}>
        {markdown}
      </Mono>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// the ones that did not build
// ---------------------------------------------------------------------------

/**
 * Why this one did not build, and what to do about it.
 *
 * A DRAFT WAS A DEAD END. The library lists it - correctly, it is something
 * you started - and opening it asked for geometry that does not exist, showed
 * an empty canvas, no size, no checks and no exports, and said nothing about
 * what had happened.
 *
 * Everything here was already on disk in run.json. The engine's diagnosis for
 * a failed cut is not "invalid spec", it is "disc in cut mode removed nothing;
 * it sits at (20.0, 0.0, -2.0) and the part spans x -20.0..15.0; set z_mm to
 * -4.00 and height_mm to 9.00" - a sentence somebody can act on, and it was
 * being thrown away.
 */
function DraftPanel({ draft }: { draft: NonNullable<PartDetail['draft']> }) {
  return (
    <>
      <Panel title="what was asked for">
        <Prose size="reading" color={core.screen}>
          {draft.request || 'not recorded'}
        </Prose>
      </Panel>

      <Panel title="why it stopped">
        {draft.message ? (
          <Prose size="body" color={core.screen}>
            {draft.message}
          </Prose>
        ) : (
          <Prose size="body" color={core.dim}>
            The run recorded no error, which usually means it was stopped rather than refused.
          </Prose>
        )}
        <Row label="attempts" value={String(draft.attempts)} />
        <Row label="time spent" value={`${draft.elapsed_s}s`} />
        {draft.level_reached !== null && draft.level_reached !== undefined ? (
          <Row label="got as far as level" value={String(draft.level_reached)} />
        ) : null}
        {draft.models.length ? (
          <Row label="models tried" value={draft.models.join(', ')} />
        ) : null}
        {draft.machine ? <Row label="machine" value={draft.machine} /> : null}
      </Panel>

      <Panel title="what to do next">
        <Prose size="body" color={core.dim}>
          Say the change below and it runs again from what it already worked out. A dimension the
          message names is the thing to put in the sentence - the engine reads a number against
          this part's own schema.
        </Prose>
      </Panel>

      {draft.spec_draft ? (
        <Panel title="the marked-up spec">
          {/* THE HANDOFF. The closest attempt with every problem written
              inline - the file somebody edits by hand to rescue the part. It
              lives on the machine at the path below. */}
          <Mono size="micro" color={core.dim}>
            {draft.handoff}
          </Mono>
          <Mono size="micro" color={core.screen} style={styles.report}>
            {draft.spec_draft}
          </Mono>
        </Panel>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    padding: space.base,
    gap: space.snug,
  },
  viewport: {
    flex: 1,
    minHeight: 220,
    borderRadius: radius.card,
    overflow: 'hidden',
  },
  bed: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bedImage: {
    width: '100%',
    height: '100%',
  },
  layoutRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  verdictBar: {
    paddingHorizontal: space.base,
    paddingVertical: space.snug,
    gap: space.snug,
  },
  drift: {
    gap: space.tight,
  },
  sheet: {
    maxHeight: '46%',
  },
  sheetBody: {
    gap: space.snug,
    paddingBottom: space.snug,
  },
  saved: {
    padding: space.snug,
  },
  option: {
    padding: space.snug,
    marginTop: space.tight,
  },
  checkRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
    paddingVertical: space.hair,
  },
  checkWord: {
    minWidth: 34,
    textAlign: 'right',
  },
  dimension: {
    paddingTop: space.snug,
    gap: space.tight,
  },
  dimensionHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  bounds: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  chain: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.tight,
  },
  chainItem: {
    minWidth: metric.tap,
    minHeight: metric.tap - space.base,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.snug,
  },
  chainSizes: {
    gap: space.hair,
    paddingTop: space.tight,
  },
  renameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  renameWell: {
    flex: 1,
    paddingHorizontal: space.snug,
  },
  actions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  pendingBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
    padding: space.snug,
  },
  tweaks: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.tight,
  },
  assumption: {
    padding: space.snug,
    gap: space.tight,
    marginTop: space.tight,
  },
  assumptionHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  grow: {
    flex: 1,
  },
  saveRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.base,
    paddingTop: space.tight,
  },
  report: {
    lineHeight: type.size.micro * 1.5,
  },
  render: {
    paddingTop: space.snug,
    gap: space.tight,
  },
  renderImage: {
    width: '100%',
    // The height map's pixel aspect matches the part, so a fixed box with
    // `contain` fitting is what keeps a tall part tall instead of stretching it.
    height: 200,
    borderRadius: radius.panel,
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
  footer: {
    flexDirection: 'row',
    gap: space.snug,
  },
  footerButton: {
    flex: 1,
  },
});
