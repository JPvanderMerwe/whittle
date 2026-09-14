/**
 * The way in, and there are two of them.
 *
 * whittle makes a part from a sentence, and whittle makes somebody else's mesh
 * editable. Neither is the real product with the other bolted on: the first is
 * what the engine has always done and the second is what build plan v8 added.
 * So they are two tabs of equal weight, not a feature behind a menu.
 *
 *   describe   words in, a built part out - the Meshy gesture, except what
 *              comes out is a parametric spec with every check run on it
 *   open       a file in, sliders out - v8's import-and-edit
 *   library    what has already been made on this machine
 *
 * RULE 31 LIVES HERE. "A template is an optimisation, never the boundary of
 * the product." Nothing on this screen offers a list of things whittle can make,
 * because presenting templates as the menu teaches people the product is a
 * catalogue. The box is empty and takes any sentence.
 *
 * THE CONNECTION IS SHOWN, NOT ASSUMED. The engine runs on a laptop and the
 * phone reaches it over `adb reverse`, so "cannot connect" is a normal state
 * with a specific cause and a specific fix. A spinner is not a diagnosis.
 */

import * as DocumentPicker from 'expo-document-picker';
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

import {
  ApiError,
  type Api,
  type Health,
  type LibraryPart,
  type Project,
  type UploadedImage,
} from '../api';
import { core, metric, pen, radius, space, type } from '../tokens';
import { Button, Mono, Panel, Problem, Prose, Row, Segmented, Surface, Verdict } from '../ui';
import { Waiting } from '../Rig';
import { uploadModel, type Progress } from '../upload';

const WAYS = ['describe', 'open a file', 'library'] as const;
type Way = (typeof WAYS)[number];

/**
 * What the file picker offers.
 *
 * Android filters on MIME type, and a downloaded STL arrives with whatever
 * type the server that sent it declared - often application/octet-stream and
 * sometimes nothing. Filtering strictly hides the user's own file from them,
 * so the picker takes anything and the SERVER decides: whittle/ingest/formats.py
 * reads the actual bytes and names what it cannot open, which is a better
 * answer than a file that cannot be selected for reasons nobody can see.
 */
const ANY_FILE = '*/*';

interface Props {
  api: Api;
  onOpened: (project: Project) => void;
  onBuilding: (jobId: string, request: string) => void;
  onPart: (name: string) => void;
}

export function StartScreen({ api, onOpened, onBuilding, onPart }: Props) {
  const [way, setWay] = useState<Way>('describe');
  const [health, setHealth] = useState<Health | null>(null);
  const [checking, setChecking] = useState(true);
  const [problem, setProblem] = useState<string | null>(null);

  const connect = useCallback(async () => {
    setChecking(true);
    setProblem(null);
    try {
      setHealth(await api.health());
    } catch (error: any) {
      setHealth(null);
      setProblem(String(error?.message ?? error));
    } finally {
      setChecking(false);
    }
  }, [api]);

  useEffect(() => {
    connect();
  }, [connect]);

  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        <View style={styles.title}>
          <Mono size="display" weight="bold" color={core.phosphor}>
            whittle
          </Mono>
          <Prose size="body" color={core.dim}>
            Describe a part and it gets built. Bring one in and it gets sliders.
          </Prose>
        </View>

        {problem ? <Problem text={problem} actionLabel="try again" onAction={connect} /> : null}

        <Machine api={api} health={health} checking={checking} />

        <Segmented options={WAYS} value={way} onChange={setWay} />

        {way === 'describe' ? (
          <Describe api={api} health={health} onBuilding={onBuilding} onProblem={setProblem} />
        ) : null}
        {way === 'open a file' ? (
          <OpenFile api={api} ready={!!health} onOpened={onOpened} onProblem={setProblem} />
        ) : null}
        {way === 'library' ? <Library api={api} ready={!!health} onPart={onPart} /> : null}

        <Surface step="well" style={styles.footer}>
          <Prose size="body" color={core.dim}>
            Nothing is uploaded anywhere. The engine is the machine this phone is plugged into,
            and the geometry never leaves it.
          </Prose>
        </Surface>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

// ---------------------------------------------------------------------------

function Machine({
  api,
  health,
  checking,
}: {
  api: Api;
  health: Health | null;
  checking: boolean;
}) {
  const bed = health?.bed as Record<string, number> | undefined;
  const printer = health?.printer as Record<string, string> | undefined;

  return (
    <Panel title="the machine">
      {checking ? (
        <Waiting caption={`asking ${api.base}`} size={96} />
      ) : health ? (
        <>
          <Verdict state="pass" text="connected" />
          {printer?.name ? <Row label="printer" value={String(printer.name)} /> : null}
          {bed?.width_mm ? (
            <Row label="bed" value={`${bed.width_mm} × ${bed.depth_mm} × ${bed.height_mm} mm`} />
          ) : (
            // RULE 29 REACHES THE SCREEN. An unmeasured value is UNSET in the
            // config and reading it raises, so the app says the bed is not
            // configured rather than drawing a default one.
            <Verdict state="warn" text="no bed configured - the bed check cannot run" />
          )}
          <Row
            label="model"
            value={health.model?.ok ? 'ready' : (health.model?.message ?? 'none')}
            valueColor={health.model?.ok ? pen.pass : core.dim}
          />
        </>
      ) : (
        <>
          <Verdict state="fail" text="not connected" />
          <Prose size="body" color={core.dim}>
            Start the engine with `whittle web`, then run `adb reverse tcp:8765 tcp:8765` on the
            machine the phone is plugged into.
          </Prose>
        </>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// words in
// ---------------------------------------------------------------------------

function Describe({
  api,
  health,
  onBuilding,
  onProblem,
}: {
  api: Api;
  health: Health | null;
  onBuilding: (jobId: string, request: string) => void;
  onProblem: (text: string | null) => void;
}) {
  const [request, setRequest] = useState('');
  const [material, setMaterial] = useState<string | null>(null);
  const [photo, setPhoto] = useState<UploadedImage | null>(null);
  const [busy, setBusy] = useState(false);

  const materials = health?.materials ?? [];
  const chosen = material ?? materials[0] ?? 'petg';

  /**
   * Attach a photo of the thing.
   *
   * The picture is measured the moment it lands - silhouette, regions - and
   * what comes back is in PIXELS. The server says so with `needs_scale` and
   * this screen repeats it, because a figure with no unit beside it is how a
   * model ends up treating 638 as millimetres.
   */
  const attach = useCallback(async () => {
    onProblem(null);
    const picked = await DocumentPicker.getDocumentAsync({
      type: 'image/*',
      copyToCacheDirectory: true,
    });
    if (picked.canceled || !picked.assets?.length) return;

    const asset = picked.assets[0];
    setBusy(true);
    try {
      const response = await fetch(asset.uri);
      const bytes = await response.arrayBuffer();
      setPhoto(await api.uploadImage(bytes, asset.mimeType ?? 'image/jpeg'));
    } catch (error: any) {
      onProblem(String(error?.message ?? error));
    } finally {
      setBusy(false);
    }
  }, [api, onProblem]);

  const make = useCallback(async () => {
    const text = request.trim();
    if (!text) return;
    setBusy(true);
    onProblem(null);
    try {
      const { job } = await api.generate(text, chosen, photo?.path);
      onBuilding(job, text);
    } catch (error: any) {
      onProblem(error instanceof ApiError ? error.message : String(error?.message ?? error));
    } finally {
      setBusy(false);
    }
  }, [api, chosen, onBuilding, onProblem, photo, request]);

  return (
    <Panel title="describe it">
      <Prose size="body" color={core.dim}>
        Say what you want in your own words, with any dimensions you know. Anything you do not
        give a number for comes back marked as an assumption.
      </Prose>

      <Surface step="well" style={styles.prompt}>
        <TextInput
          value={request}
          onChangeText={setRequest}
          multiline
          placeholder="a wall bracket for a 35 mm pipe, 4 mm thick, two M4 screw holes 60 mm apart"
          placeholderTextColor={core.dim}
          style={styles.promptInput}
        />
      </Surface>

      {materials.length ? (
        <View style={styles.materialRow}>
          <Mono size="label" color={core.dim}>
            material
          </Mono>
          <View style={styles.chips}>
            {materials.map((name) => (
              <Pressable
                key={name}
                onPress={() => setMaterial(name)}
                style={[styles.chip, name === chosen && styles.chipOn]}>
                <Mono size="label" color={name === chosen ? core.phosphor : core.dim}>
                  {name}
                </Mono>
              </Pressable>
            ))}
          </View>
        </View>
      ) : null}

      {photo ? (
        <Surface step="well" style={styles.photo}>
          <Row label="photo" value={photo.name} />
          {photo.needs_scale ? (
            <Verdict
              state="warn"
              text="measured in pixels - give one real dimension in the words above and the rest scales"
            />
          ) : null}
          {photo.note ? (
            <Prose size="body" color={core.dim}>
              {photo.note}
            </Prose>
          ) : null}
          <Button label="remove the photo" onPress={() => setPhoto(null)} />
        </Surface>
      ) : (
        <Button label="attach a photo" onPress={attach} disabled={!health || busy} />
      )}

      <Button
        label={busy ? 'asking the machine…' : 'make it'}
        primary
        onPress={make}
        disabled={!health || busy || !request.trim()}
      />
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// a file in
// ---------------------------------------------------------------------------

function OpenFile({
  api,
  ready,
  onOpened,
  onProblem,
}: {
  api: Api;
  ready: boolean;
  onOpened: (project: Project) => void;
  onProblem: (text: string | null) => void;
}) {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [working, setWorking] = useState<string | null>(null);

  const pick = useCallback(async () => {
    onProblem(null);
    const picked = await DocumentPicker.getDocumentAsync({
      type: ANY_FILE,
      copyToCacheDirectory: true,
    });
    if (picked.canceled || !picked.assets?.length) return;

    const asset = picked.assets[0];
    setWorking(asset.name);
    setProgress({ sent: 0, total: asset.size ?? 0 });
    try {
      onOpened(await uploadModel(api, asset.uri, asset.name, setProgress));
    } catch (error: any) {
      onProblem(error instanceof ApiError ? error.message : String(error?.message ?? error));
    } finally {
      setWorking(null);
      setProgress(null);
    }
  }, [api, onOpened, onProblem]);

  return (
    <Panel title="open a file">
      <Prose size="body" color={core.dim}>
        An STL, OBJ, PLY or glTF - anything off Printables, Thingiverse or Meshy. whittle reads
        it, repairs what it can, says what it cannot, and gives you sliders.
      </Prose>

      {working ? (
        <View style={styles.progress}>
          {/* THE FRACTION WHILE IT IS SENDING, AND NONE AFTER. Once the bytes
              are up the server is running repair, the gate and a thickness
              measurement over every triangle, and none of that reports a
              percentage - so the bar stops rather than inventing one. */}
          <Waiting
            caption={
              progress && progress.total && progress.sent < progress.total
                ? `sending ${working}`
                : 'reading it - repair, then every check'
            }
            fraction={
              progress && progress.total && progress.sent < progress.total
                ? progress.sent / progress.total
                : undefined
            }
          />
        </View>
      ) : (
        <Button label="choose a file" primary onPress={pick} disabled={!ready} />
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// what has been made already
// ---------------------------------------------------------------------------

function Library({
  api,
  ready,
  onPart,
}: {
  api: Api;
  ready: boolean;
  onPart: (name: string) => void;
}) {
  const [parts, setParts] = useState<LibraryPart[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    api
      .parts()
      .then((r) => setParts(r.parts))
      .catch((error) => setFailed(String(error?.message ?? error)));
  }, [api, ready]);

  if (failed) return <Panel title="library">{<Verdict state="fail" text={failed} />}</Panel>;
  if (!parts) {
    return (
      <Panel title="library">
        <Waiting caption="reading the library" size={96} />
      </Panel>
    );
  }
  if (parts.length === 0) {
    return (
      <Panel title="library">
        <Prose size="body" color={core.dim}>
          Nothing built on this machine yet.
        </Prose>
      </Panel>
    );
  }

  return (
    <>
      {parts.map((part) => (
        <Pressable key={part.name} onPress={() => onPart(part.name)}>
          <Panel>
            <Mono size="label" weight="medium">
              {part.name}
            </Mono>
            {part.prompt ? (
              <Prose size="body" color={core.dim}>
                {part.prompt}
              </Prose>
            ) : null}
            {part.size_mm ? (
              <Row label="size" value={`${part.size_mm.join(' × ')} mm`} />
            ) : null}
            {/* PIECES, not a guess. A null body count means the part was built
                before that was recorded, and "1 piece" for it would be an
                invention - which for anything with a moving part is the fact
                that decides whether it works. */}
            {part.bodies ? (
              <Row label="pieces" value={String(part.bodies)} />
            ) : null}
            {part.material ? <Row label="material" value={part.material} /> : null}
          </Panel>
        </Pressable>
      ))}
    </>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
  },
  body: {
    padding: space.base,
    gap: space.base,
  },
  title: {
    paddingTop: space.loose,
    paddingBottom: space.snug,
    gap: space.tight,
  },
  prompt: {
    padding: space.snug,
  },
  promptInput: {
    minHeight: metric.tap * 2,
    color: core.screen,
    fontFamily: type.mono,
    fontSize: type.size.body,
    textAlignVertical: 'top',
  },
  materialRow: {
    gap: space.tight,
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
  chipOn: {
    borderColor: core.phosphor,
  },
  photo: {
    padding: space.snug,
    gap: space.snug,
  },
  progress: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.base,
    paddingVertical: space.snug,
  },
  progressText: {
    flex: 1,
  },
  footer: {
    padding: space.base,
  },
});
