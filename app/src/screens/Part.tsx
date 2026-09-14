/**
 * A built part: what it is, whether it passed, and what else it could have been.
 *
 * Reached two ways - straight off a build, or out of the library - so it takes
 * a name and fetches the rest. The geometry goes through the SAME viewport the
 * imports use: one renderer, one GLB reader, one set of eyes on whether it
 * draws.
 *
 * THE VERDICT IS THE HEADLINE, and the problems are quoted in the engine's own
 * words. A part that failed verification still gets shown - it exists, it is on
 * disk, and hiding it would leave somebody with a build that "did nothing".
 * What it does not get is a green tick.
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';

import { ApiError, type Api, type BuiltPart, type PartOption, type Project } from '../api';
import { core, metric, pen, space, type } from '../tokens';
import { Rig } from '../Rig';
import { Button, Mono, Panel, Problem, Prose, Row, Surface, Verdict } from '../ui';
import { Viewport } from '../Viewport';

interface Props {
  api: Api;
  /** The part to show. Changing it reloads everything, which is how options work. */
  name: string;
  /** Present when we just built it; absent when it came out of the library. */
  built?: BuiltPart;
  onClose: () => void;
  /** A change was asked for in English; watch it rebuild. */
  onChanging: (jobId: string, instruction: string) => void;
  /** Put sliders on it. */
  onEdit: (project: Project) => void;
}

export function PartScreen({ api, name, built, onClose, onChanging, onEdit }: Props) {
  const [instruction, setInstruction] = useState('');
  const [busy, setBusy] = useState(false);
  const [showing, setShowing] = useState(name);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [glb, setGlb] = useState<ArrayBuffer | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    setShowing(name);
  }, [name]);

  useEffect(() => {
    let live = true;
    setGlb(null);
    setDetail(null);
    setProblem(null);

    api
      .part(showing)
      .then((d) => live && setDetail(d))
      .catch((error) => live && setProblem(String(error?.message ?? error)));

    api
      .partGlb(showing)
      .then((bytes) => live && setGlb(bytes))
      .catch((error) => live && setProblem(String(error?.message ?? error)));

    return () => {
      live = false;
    };
  }, [api, showing]);

  // The build's own payload is richer than the library's, but only for the
  // part that was just built - an option is a different part and has to be
  // read off disk like any other.
  const fresh = built && (showing === built.dir || showing === built.name) ? built : undefined;
  // A PART ON DISK MAY HAVE NO STORED VERDICT - it predates run.json, or it
  // was imported rather than generated. That is "not known", which is not the
  // same as "failed", and showing a red cross over a part that was never
  // checked is the kind of false alarm that teaches people to ignore verdicts.
  const stored = (detail?.checks as { verdict?: string } | undefined)?.verdict;
  const verdict = fresh?.verdict ?? (detail?.verdict as string) ?? stored ?? '';
  const known = Boolean(verdict);
  const passed = fresh ? fresh.ok : verdict.toLowerCase().includes('pass');

  const size = (fresh?.size_mm ?? (detail?.size_mm as number[] | undefined)) ?? null;
  const bodies = fresh?.bodies ?? (detail?.bodies as number | undefined) ?? null;
  const volume = fresh?.volume_cm3 ?? (detail?.volume_cm3 as number | undefined) ?? null;
  const problems = fresh?.problems ?? [];
  const warnings = fresh?.warnings ?? [];
  const assumptions = fresh?.assumptions ?? [];
  const options: PartOption[] = fresh?.options ?? [];

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
      onChanging(job, text);
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

  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={styles.header}>
        <Pressable onPress={onClose} hitSlop={space.base} style={styles.back}>
          <Mono size="label" color={core.dim}>
            ‹ start
          </Mono>
        </Pressable>
        <View style={styles.headerText}>
          <Mono size="label" weight="medium" numberOfLines={1}>
            {fresh?.name ?? (detail?.spec as { name?: string })?.name ?? showing}
          </Mono>
          {/* The directory, when it is not the same as the name - so it is
              always possible to tell two refinements of one part apart. */}
          {showing !== ((fresh?.name ?? (detail?.spec as { name?: string })?.name) ?? showing) ? (
            <Mono size="micro" color={core.dim}>
              {showing}
            </Mono>
          ) : null}
          {fresh?.elapsed_s !== undefined ? (
            <Mono size="micro" color={core.dim}>
              built in {fresh.elapsed_s}s over {fresh.attempts ?? 1} attempt
              {(fresh.attempts ?? 1) === 1 ? '' : 's'}
            </Mono>
          ) : null}
        </View>
        {busy ? <Rig size={40} /> : null}
      </View>

      <View style={styles.viewport}>
        <Viewport glb={glb} placeholder="fetching the geometry…" />
      </View>

      <Surface step="pill" style={styles.verdictBar}>
        <Verdict
          state={!known ? 'waiting' : passed ? 'pass' : 'fail'}
          text={known ? verdict : 'built before this machine recorded verdicts - not re-checked'}
        />
      </Surface>

      <ScrollView style={styles.sheet} contentContainerStyle={styles.sheetBody}>
        {problem ? <Problem text={problem} /> : null}

        <Panel title="measured">
          {size ? <Row label="size" value={`${size.join(' × ')} mm`} /> : null}
          {volume !== null ? <Row label="volume" value={`${volume} cm³`} /> : null}
          {bodies !== null ? <Row label="pieces" value={String(bodies)} /> : null}
          {fresh?.watertight !== undefined && fresh.watertight !== null ? (
            <Row
              label="watertight"
              value={fresh.watertight ? 'yes' : 'no'}
              valueColor={fresh.watertight ? pen.pass : pen.fail}
            />
          ) : null}
          {fresh?.material ? <Row label="material" value={fresh.material} /> : null}
          {fresh?.template ? <Row label="template" value={fresh.template} /> : null}
          {fresh?.files?.length ? <Row label="files" value={fresh.files.join(', ')} /> : null}
        </Panel>

        {problems.map((text, index) => (
          <Panel key={`p${index}`}>
            <Verdict state="fail" text={text} />
          </Panel>
        ))}
        {warnings.map((text, index) => (
          <Panel key={`w${index}`}>
            <Verdict state="warn" text={text} />
          </Panel>
        ))}

        {assumptions.length ? (
          <Panel title="assumptions">
            {/* RULE 14. Anything that could not be measured is a named
                parameter marked ASSUMPTION, and it appears under a heading
                that says so rather than blending into the measurements. */}
            {assumptions.map((text, index) => (
              <Prose key={index} size="body" color={core.dim}>
                · {text}
              </Prose>
            ))}
          </Panel>
        ) : null}

        {options.length > 1 ? (
          <Panel title="other ways it could have gone">
            <Prose size="body" color={core.dim}>
              Built by walking the spec's own axes, so they cost seconds rather than another
              trip through the model.
            </Prose>
            {options.map((option) => (
              <Pressable key={option.name} onPress={() => setShowing(option.name)}>
                <Surface
                  step="well"
                  style={[
                    styles.option,
                    option.name === showing && { borderColor: core.phosphor },
                  ]}>
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

        {typeof detail?.report_md === 'string' && detail.report_md ? (
          <Panel title="the report">
            <Prose size="body" color={core.dim}>
              {String(detail.report_md).slice(0, 4000)}
            </Prose>
          </Panel>
        ) : null}
      </ScrollView>

      {/* SAY WHAT TO CHANGE. Not a parameter list - the sentence goes to the
          engine, which reads it against this part's own template. */}
      <Surface step="pill" style={styles.command}>
        <TextInput
          value={instruction}
          onChangeText={setInstruction}
          onSubmitEditing={change}
          returnKeyType="send"
          placeholder="make this roof a triangular roof"
          placeholderTextColor={core.dim}
          style={styles.input}
        />
        <Button label="change it" primary onPress={change} disabled={!instruction.trim() || busy} />
      </Surface>

      <View style={styles.footer}>
        <Button label="sliders" onPress={edit} disabled={busy} style={styles.footerButton} />
        <Button label="back" onPress={onClose} style={styles.footerButton} />
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    padding: space.base,
    gap: space.snug,
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
  option: {
    padding: space.snug,
    marginTop: space.tight,
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
