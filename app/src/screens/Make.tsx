/**
 * Where you land. One question, one box, one button - and three things a
 * generic AI-3D tool cannot put on its first screen.
 *
 * MESHY'S LANDING, AND WHY COPYING IT WOULD NOT BE GOOD ENOUGH
 * ------------------------------------------------------------
 * Their workspace asks one question over one input, with a mode rail down the
 * left and the asset gallery beside it. The composition is right and it is
 * taken: the question is the hero, the box is the hero control, "make it" is
 * the only filled button, and every setting is folded away.
 *
 * But that shape is generic - it is the same screen every text-to-something
 * product ships, and it is generic because a hosted generator has nothing
 * specific to say. This one does, and the three things it can say are the
 * three things that make the screen better rather than merely similar:
 *
 *   1. WHAT THIS WILL BE MEASURED AGAINST. "Creality i7 · 260 × 260 × 255 mm
 *      bed · 0.4 mm nozzle · petg", under the button, before anything is
 *      asked for. Every verdict this engine gives is measured against a real
 *      machine, and Meshy cannot write that line because it does not know
 *      what you are going to print with. It costs one row and it is the
 *      single most honest thing on the screen.
 *
 *   2. WHAT THE MACHINE IS DOING RIGHT NOW. A build outlives the screen that
 *      started it, so if one is running it belongs at the top of the first
 *      screen, with the engine's own last word on it - not buried in a tab.
 *
 *   3. WHAT YOU WERE LAST DOING. A gallery is the right answer on a desktop
 *      with a whole column to spare. On a phone the useful version is one
 *      card: the last part, its picture, its verdict, one tap back into it.
 *      The gallery is a tab away and stays a tab away.
 *
 * WHAT IS DELIBERATELY NOT COPIED. Meshy prices its Generate button in
 * credits. Whittle runs on the machine in front of you and costs nothing per
 * model, so there is no number to put there and inventing one would be
 * dishonest.
 *
 * RULE 31 AND THE EXAMPLES, BECAUSE THIS IS THE LINE TO BE CAREFUL ABOUT.
 * Nothing here offers a list of things whittle can make. What the empty box
 * gets is three ways of SAYING something - a size, a fit, a material - which
 * teach the grammar rather than a catalogue, are chosen so that none of them
 * is a template, and put the words in the box for editing rather than
 * submitting them. Rule 32 is why they are there at all: English is the
 * interface, and an empty box with no hint at all is an interface that only
 * works for somebody who has read the schema.
 */

import * as DocumentPicker from 'expo-document-picker';
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
  type Health,
  type LibraryPart,
  type MachineJob,
  type Project,
  type UploadedImage,
} from '../api';
import { measuredAgainst, nowrap } from '../machine';
import { core, glass, metric, pen, radius, space, type } from '../tokens';
import { Waiting } from '../Rig';
import {
  Button,
  Chip,
  Mono,
  Panel,
  Problem,
  Prose,
  Quiet,
  Surface,
  Verdict,
} from '../ui';
import { bringManyIn, uploadModel, type Brought, type Progress } from '../upload';
import { Press } from '../motion';

/**
 * What the file picker offers.
 *
 * EVERYTHING, and the server decides. Android filters on MIME type, and a
 * downloaded STL arrives with whatever the browser guessed - very often
 * application/octet-stream, sometimes nothing at all. Filtering to model types
 * here greyed out the exact files this screen exists to open. The server reads
 * the magic bytes rather than the name, so a wrong pick is a clear refusal.
 */
const ANY_FILE = '*/*';

/** The turntable step a thumbnail uses. Three-quarter view, like the mark. */
const THUMB_STEP = 3;

/**
 * What a first request actually looks like.
 *
 * THESE WERE WRONG AND THE OWNER SAID SO. They used to read "a bracket for a
 * 35 mm pipe, 4 mm thick, two M4 holes 60 mm apart" - an engineering
 * specification, which is not what anybody types and not what this product
 * asks for. Nobody arrives knowing the dimensions. They arrive knowing they
 * want a bracket.
 *
 * THAT IS THE WORKFLOW, not a concession to it: say the thing, the engine
 * builds a good one and marks every number it had to choose, and then it gets
 * changed until it is right - by saying so, or with sliders. Putting a
 * dimensioned sentence on the first screen teaches exactly the wrong lesson,
 * which is that you have to know the answer before you start.
 *
 * NOT A MENU either - see the note at the top of this file. Two words each, so
 * they read as the SHAPE of a request rather than as a list of things whittle
 * can make, and the line above them says the box takes any sentence.
 */
const WAYS_TO_SAY = ['a bracket', 'a phone stand', 'a box with a lid', 'a hook'];

interface Props {
  api: Api;
  health: Health | null;
  checking: boolean;
  jobs: MachineJob[];
  parts: LibraryPart[] | null;
  /** Whichever material was chosen last, or null for the machine's first. */
  material: string | null;
  onMaterial: (name: string) => void;
  onOpened: (project: Project) => void;
  onBuilding: (jobId: string, request: string) => void;
  onPart: (dir: string) => void;
  onWatch: (jobId: string, request: string) => void;
  /** No machine to talk to: the Machine tab is where that gets fixed. */
  onFixConnection: () => void;
  /** Everything made, which is a tab rather than a panel. */
  onSeeAll: () => void;
  /**
   * The gallery sent somebody here to bring a file in.
   *
   * The importer lives on this screen because the upload progress and the
   * ingest report are already wired here; the gallery has the button because
   * that is where the files are. One flow, two ways in.
   */
  openFileNow?: boolean;
  onOpenedFilePicker?: () => void;
  /**
   * A batch of files has landed in the library.
   *
   * The screen that owns the library list has to be told: a batch import
   * adds forty entries without any build finishing, and the polling that
   * usually notices runs on its own clock. Optional, so a caller that does
   * not hold the list does not have to pretend to.
   */
  onImported?: () => Promise<void> | void;
  /**
   * A file somebody shared into whittle from elsewhere on the phone.
   *
   * It arrives already copied into this app's cache by the share module, so
   * there is no picker to open - it goes straight up the same route a picked
   * file does, through the same progress and the same ingest report.
   */
  incoming?: { uri: string; name: string } | null;
  onTookIncoming?: () => void;
}

export function MakeScreen({
  api,
  health,
  checking,
  jobs,
  parts,
  material,
  onMaterial,
  onOpened,
  onBuilding,
  onPart,
  onWatch,
  onFixConnection,
  onSeeAll,
  openFileNow,
  onOpenedFilePicker,
  onImported,
  incoming,
  onTookIncoming,
}: Props) {
  const [request, setRequest] = useState('');
  const [photo, setPhoto] = useState<UploadedImage | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [working, setWorking] = useState<string | null>(null);
  /**
   * How far through a batch import we are, and what came of it.
   *
   * ONE FILE WAS THE WHOLE STORY UNTIL NOW: the picker took one, opened an
   * editing session on it and put you in it. That is the right flow for
   * bringing in a model to work on and hopeless for filling a library from
   * a downloads folder, which is the thing somebody actually does after
   * finding forty models they like.
   */
  const [batch, setBatch] = useState<{ done: number; total: number; name: string } | null>(null);
  const [brought, setBrought] = useState<Brought[] | null>(null);
  const [focused, setFocused] = useState(false);
  const [more, setMore] = useState(false);

  const materials = health?.materials ?? [];
  // Never materials[0] - see Health.material_default.
  const chosen = material ?? health?.material_default ?? null;
  const ready = Boolean(health);
  const profile = measuredAgainst(health, material);

  /**
   * NOTHING MADE YET, so the screen is allowed to explain itself.
   *
   * THE LANDING SCREEN WAS A WALL OF WORDS. Hero, composer, profile line, a
   * label over the examples, a four-line paragraph about how the loop works,
   * and a two-line footnote about privacy - every one of them true, and
   * together they buried the one control the screen exists for. Meshy's is a
   * question, a box and a button; that is the bar, and more words is not how
   * you clear it.
   *
   * But the explanation is not noise for somebody who has never done this:
   * "you do not need dimensions" is the single thing a first-timer cannot
   * guess and every other decision on the screen depends on. So it is said
   * ONCE, to the person who needs it, and gone the moment they have made
   * something - because by then they have watched it happen.
   *
   * Null parts is "not read yet", which is not the same as none: showing the
   * first-run copy for a second on every cold start is the flicker this
   * distinction exists to avoid.
   */
  const firstTime = parts !== null && parts.length === 0;

  const running = jobs.filter((job) => !job.done);
  // The library is served newest first, so the most recent is simply the head.
  // Sorting it here would be a second opinion about an order the server has.
  //
  // AND IT IS THE NEWEST THING, NOT THE NEWEST SUCCESSFUL ONE. Filtering to
  // built parts put a card headed "the last thing you made" over something
  // from last week whenever the actual last thing was a draft - and a build
  // that failed is precisely what a person wants to get back to.
  const recent = (parts ?? [])[0];

  /**
   * The handful worth putting on the shelf.
   *
   * NEWEST FIRST, WHICH IS THE ORDER THE ENGINE SERVES - re-sorting here
   * would be a second opinion about something it has already decided.
   *
   * EIGHT, because this is a reminder rather than the gallery: enough that
   * the row obviously scrolls, few enough that it never becomes the thing
   * you browse in. The gallery is a tab and stays a tab.
   */
  const shelf = (parts ?? []).slice(0, 8);

  const attach = useCallback(async () => {
    setProblem(null);
    const picked = await DocumentPicker.getDocumentAsync({
      type: 'image/*',
      copyToCacheDirectory: true,
    });
    if (picked.canceled || !picked.assets?.length) return;
    const asset = picked.assets[0];
    setBusy(true);
    try {
      const response = await fetch(asset.uri);
      setPhoto(
        await api.uploadImage(await response.arrayBuffer(), asset.mimeType ?? 'image/jpeg'),
      );
    } catch (error: any) {
      setProblem(String(error?.message ?? error));
    } finally {
      setBusy(false);
    }
  }, [api]);

  const make = useCallback(async () => {
    const text = request.trim();
    if (!text) return;
    setBusy(true);
    setProblem(null);
    try {
      // THE MATERIAL IS THE MACHINE'S OR NOTHING. A client default of 'petg'
      // sends a generate naming a material the config may not have, and the
      // failure surfaces as a refusal nobody can connect to a control they
      // never touched. Empty string lets the engine use its own.
      const { job } = await api.generate(text, chosen ?? '', photo?.path);
      setRequest('');
      setPhoto(null);
      onBuilding(job, text);
    } catch (error: any) {
      setProblem(error instanceof ApiError ? error.message : String(error?.message ?? error));
    } finally {
      setBusy(false);
    }
  }, [api, chosen, onBuilding, photo, request]);

  /**
   * Send one file up and open what comes back.
   *
   * ONE PATH FOR BOTH WAYS IN. A file picked here and a file shared in from
   * another app are the same bytes and deserve the same progress, the same
   * ingest report and the same failure message - so the picker and the share
   * receiver both end here rather than growing two copies that drift.
   */
  const send = useCallback(
    async (uri: string, name: string, size?: number) => {
      setProblem(null);
      setWorking(name);
      setProgress({ sent: 0, total: size ?? 0 });
      try {
        onOpened(await uploadModel(api, uri, name, setProgress));
      } catch (error: any) {
        setProblem(error instanceof ApiError ? error.message : String(error?.message ?? error));
      } finally {
        setWorking(null);
        setProgress(null);
      }
    },
    [api, onOpened],
  );

  const openFile = useCallback(async () => {
    setProblem(null);
    setBrought(null);
    const picked = await DocumentPicker.getDocumentAsync({
      type: ANY_FILE,
      copyToCacheDirectory: true,
      // MANY, BECAUSE THAT IS WHAT PEOPLE HAVE. Somebody who has been
      // collecting models off Printables and Thingiverse has a folder of
      // them, and importing one at a time is forty trips through a picker.
      multiple: true,
    });
    if (picked.canceled || !picked.assets?.length) return;

    // ONE FILE STILL OPENS IT. Bringing in a single model means working on
    // it - the editor, the measurements, the whole screen - and routing that
    // through the batch importer would land somebody in a summary of one.
    if (picked.assets.length === 1) {
      const asset = picked.assets[0];
      await send(asset.uri, asset.name, asset.size ?? undefined);
      return;
    }

    const files = picked.assets.map((asset) => ({ uri: asset.uri, name: asset.name }));
    setBatch({ done: 0, total: files.length, name: files[0]?.name ?? '' });
    try {
      const results = await bringManyIn(api, files, [], (done, total, name) =>
        setBatch({ done, total, name }),
      );
      setBrought(results);
      // THE LIBRARY HAS CHANGED, and the gallery is where they now are.
      await onImported?.();
    } catch (error: any) {
      setProblem(error instanceof ApiError ? error.message : String(error?.message ?? error));
    } finally {
      setBatch(null);
    }
  }, [api, onImported, send]);

  // SHARED IN FROM SOMEWHERE ELSE. Acknowledged on the edge before the upload
  // starts, so a slow import cannot be started twice by a re-render.
  useEffect(() => {
    if (!incoming) return;
    onTookIncoming?.();
    send(incoming.uri, incoming.name);
  }, [incoming, onTookIncoming, send]);

  // ASKED FOR FROM THE GALLERY. Fired once, on the edge, and acknowledged
  // immediately - leaving the flag set would re-open a picker on every later
  // visit to this tab.
  useEffect(() => {
    if (!openFileNow) return;
    onOpenedFilePicker?.();
    openFile();
  }, [openFileNow, onOpenedFilePicker, openFile]);

  // An import takes over the screen while it runs: the bytes go up, then the
  // server repairs, gates and measures, and none of that is something to do
  // alongside typing a new sentence.
  // A BATCH TAKES OVER THE SCREEN, like a single import does, and for the
  // same reason: the machine is tessellating and measuring a mesh at a time,
  // and there is nothing else useful to do while it does.
  if (batch) {
    return (
      <View style={styles.centre}>
        <Waiting
          caption={`bringing in ${batch.done + 1} of ${batch.total}${
            batch.name ? ` - ${batch.name}` : ''
          }`}
          fraction={batch.total ? batch.done / batch.total : undefined}
        />
        <Prose size="body" color={core.dim} style={styles.middle}>
          Each one is measured on the way in - its size, whether it is closed, how many pieces -
          so it can be found and worked on later. Leave it running.
        </Prose>
      </View>
    );
  }

  if (working) {
    return (
      <View style={styles.centre}>
        <Waiting
          caption={
            progress && progress.total && progress.sent < progress.total
              ? `reading ${working}`
              : 'checking it over - repair, then every check'
          }
          fraction={
            progress && progress.total && progress.sent < progress.total
              ? progress.sent / progress.total
              : undefined
          }
        />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        {/* THE SCREEN ASSEMBLES ITSELF, briefly.
            Not decoration: on a cold start this screen waits on the engine
            for its printer line and its last part, so without motion the
            page lands in two or three jumps as each answer arrives. A short
            rise on each block makes that read as the page filling in rather
            than as it flickering. Under 200 ms, a few pixels, and skipped
            entirely for anybody who has asked their phone for less
            movement - see src/motion.tsx. */}
        {/* THE BRAND AND THE STATE, ON ONE ROW. A person should always know
            what they are looking at and whether it can do anything, and those
            are two facts, not two panels. The state is a tap into the machine
            tab because that is the only place it can be acted on. */}
        <View style={styles.brandRow}>
          <Image source={require('../../assets/mark.png')} style={styles.mark} />
          {/* THE WORDMARK IS THE DRAWING, NOT THE STRING.
              This was `<Prose>whittle</Prose>`, and Prose on Android resolves
              to `sans-serif` - the system face. So the brand could be set in
              Space Grotesk, in Ubuntu or in JetBrains Mono and the phone's
              first screen looked identical either way: every decision about
              the wordmark's face was invisible exactly where it matters most.

              A logotype is a drawing. This is the same outline the web client
              and the splash screen use, generated by whittle_media, with its
              letterspacing and its weight already in it - so the name cannot
              drift between the three places it appears. */}
          <Image
            source={require('../../assets/wordmark.png')}
            style={styles.wordmark}
            resizeMode="contain"
          />
          <View style={styles.grow} />
          <Pressable onPress={onFixConnection} hitSlop={space.base} style={styles.state}>
            <View
              style={[
                styles.dot,
                { backgroundColor: checking ? core.dim : ready ? pen.pass : pen.fail },
              ]}
            />
            <Mono size="micro" color={core.dim}>
              {checking ? 'finding it' : ready ? 'connected' : 'offline'}
            </Mono>
          </Pressable>
        </View>

        {/* THE QUESTION. Two lines rather than one, because at display size a
            single line either wraps badly or has to be shortened into
            something blander.

            AND IT IS PROSE, NOT MONO. It was set in the mono family, which
            made the largest thing on the first screen a monospace sentence -
            the exact "developer tool" read the whole brand was moved away
            from. The tokens are explicit about which is which: mono is for
            labels, parameters, numbers and dimensions; prose is for anything
            a person reads as a sentence. A question is a sentence. */}
        <View style={styles.hero}>
          <Prose size="display" weight="bold" color={core.screen}>
            What do you
          </Prose>
          <Prose size="display" weight="bold" color={core.screen}>
            want to make?
          </Prose>
        </View>

        {!ready && !checking ? (
          <Surface step="well" style={styles.offline}>
            <Verdict state="fail" text="not connected to the machine" />
            <Prose size="body" color={core.dim}>
              Nothing can be built until the app can reach the computer running whittle.
            </Prose>
            <Button label="set it up" primary onPress={onFixConnection} />
          </Surface>
        ) : null}

        {problem ? <Problem text={problem} /> : null}

        {/* WHAT CAME OF A BATCH, AND WHAT DID NOT.
            A downloads folder has a README and three ZIPs in it. The import
            does not stop at them - it would mean the other thirty-nine never
            arrive - so the ones it could not take are named here instead.
            Saying "41 brought in" and silently dropping three is how a person
            later finds a model missing and has no idea when. */}
        {brought ? (
          <Panel title={`${brought.filter((one) => one.ok).length} brought in`}>
            {brought.some((one) => !one.ok) ? (
              <>
                <Verdict
                  state="warn"
                  text={`${brought.filter((one) => !one.ok).length} could not be taken in`}
                />
                {brought
                  .filter((one) => !one.ok)
                  .slice(0, 6)
                  .map((one) => (
                    <Mono key={one.filename} size="micro" color={core.dim} numberOfLines={2}>
                      {one.filename} - {one.why}
                    </Mono>
                  ))}
              </>
            ) : (
              <Verdict state="pass" text="every file was measured and filed" />
            )}
            <Quiet label="see them in your models ›" color={core.phosphor} onPress={onSeeAll} />
          </Panel>
        ) : null}

        {/* THE COMPOSER. It takes a focus ring in phosphor rather than a
            colour change on the text, because the box is the hero control and
            the one thing a hero control must do is look like the place your
            finger goes. */}
        <Surface
          step="panel"
          style={[
            styles.composer,
            focused && styles.composerFocused,
            focused && { borderColor: core.phosphor },
          ]}>
          <TextInput
            value={request}
            onChangeText={setRequest}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            multiline
            placeholder="a birdhouse"
            placeholderTextColor={core.dim}
            style={styles.prompt}
          />

          {photo ? (
            <FromPhoto
              photo={photo}
              onRemove={() => setPhoto(null)}
              onScale={(sentence) =>
                setRequest((current) =>
                  current.trim() ? `${current.trim()}, ${sentence}` : sentence,
                )
              }
            />
          ) : null}

          <View style={styles.rule} />

          {/* THE THREE WAYS IN, SIDE BY SIDE, AND THE THIRD WAS MISSING.
              There are exactly three ways to start something here: describe
              it, photograph it, or bring a model you already have. Two of
              them were on this screen and the third - the one somebody with
              a folder of downloads needs first - was a text link on the
              GALLERY, which is a screen you only visit once you already have
              something. So "bring in an STL you already have" was a feature
              you had to be told about.

              Sized by how often each is the answer rather than by
              importance: the box above is the way in, so "make it" is the
              filled control, and the other two are the same height beside
              it. The hierarchy is one being filled and the others not,
              rather than one being faint. */}
          <View style={styles.actions}>
            <Button
              label={photo ? 'change photo' : '+ photo'}
              onPress={attach}
              disabled={!ready || busy}
            />
            <Button label="+ stl" onPress={openFile} disabled={!ready || busy} />
            <View style={styles.grow} />
            <Button
              label={busy ? 'asking…' : 'make it'}
              primary
              onPress={make}
              disabled={!ready || busy || !request.trim()}
            />
          </View>
        </Surface>

        {/* WHAT IT WILL BE MEASURED AGAINST - ONE LINE, NOT FOUR.
            This is still the best thing on the screen and the one a hosted
            generator cannot write: every verdict is measured against a real
            printer with a real nozzle. But it was a labelled block in full
            brightness taking four lines above the examples, and to somebody
            opening this for the first time "Creality i7 · 260 × 260 × 255 mm
            bed · 0.4 mm nozzle · petg" is four facts they did not ask for
            between them and the thing they came to do.

            So it is one dim line that still says all of it, still taps
            through to the machine screen, and no longer competes with the
            question at the top. */}
        {/* THE EXAMPLES, ONLY WHILE THE BOX IS EMPTY. They put words in the
            box to edit; nothing is submitted on a tap. See the rule 31 note at
            the top of this file. */}
        {ready && !request.trim() ? (
          <View style={styles.block}>
            <Mono size="micro" color={core.dim}>
              or start from one of these
            </Mono>
            <View style={styles.examples}>
              {WAYS_TO_SAY.map((line) => (
                <Chip key={line} label={line} onPress={() => setRequest(line)} />
              ))}
            </View>
            {/* THE LOOP, SAID ONCE, TO THE PERSON WHO NEEDS IT. Without this
                an empty box implies that whatever you type is the only chance
                you get, which is the opposite of how this works. Three lines
                cut to one, and shown only until they have made something. */}
            {firstTime ? (
              <Prose size="body" color={core.dim}>
                No dimensions needed - it picks sensible ones, shows its working, and you change
                it afterwards by saying so.
              </Prose>
            ) : null}
          </View>
        ) : null}

        {/* THE PRINTER, AS A FOOTER.
            It was between the box and the examples, which put a line of
            settings across the one path through this screen: read the
            question, type in the box, or tap an example. It is still the
            best thing on the screen and the one a hosted generator cannot
            write - it is simply not a step in that path, so it sits with
            the other settings at the bottom and still taps through. */}
        {profile.length ? (
          <Pressable onPress={onFixConnection}>
            <Mono size="micro" color={core.dim} style={styles.profileLine} numberOfLines={1}>
              {`measured against ${profile.map(nowrap).join('  ·  ')}`}
            </Mono>
          </Pressable>
        ) : null}

        {/* 2. WHAT THE MACHINE IS DOING. Above the library card, because a
            build in flight is more urgent than one that finished. */}
        {running.length ? (
          <View style={styles.block}>
            <Mono size="micro" color={core.dim}>
              building now
            </Mono>
            {running.map((job) => (
              <Pressable key={job.id} onPress={() => onWatch(job.id, job.request)}>
                <Surface step="card" style={styles.job}>
                  <View style={styles.jobHead}>
                    <Mono size="label" weight="medium" numberOfLines={1} style={styles.grow}>
                      {job.request || job.kind}
                    </Mono>
                    <Mono size="micro" color={core.phosphor}>
                      {Math.round(job.elapsed_s)}s
                    </Mono>
                  </View>
                  {/* The engine's own last word, not a stage this screen
                      decided the job must be at. */}
                  <Mono size="micro" color={core.dim} numberOfLines={1}>
                    {job.note || 'starting'}
                  </Mono>
                </Surface>
              </Pressable>
            ))}
          </View>
        ) : null}

        {/* 3. WHAT YOU HAVE MADE - A ROW, NOT ONE CARD.
            This was a single card headed "the last thing you made", and
            below it the screen simply stopped: on a tall phone, a third of
            the page was empty. One card is also the least useful shape for
            the thing it is for - somebody comes back to this screen to get
            at something they made, and which one they want is rarely the
            most recent.

            A ROW THAT SCROLLS SIDEWAYS, not a grid: the gallery is a tab and
            stays a tab, and a grid here would be a second one competing with
            it. Sideways says "there are more of these, and they are over
            there" without taking the vertical space the composer needs.

            PICTURES ONLY, WITH THE NAME UNDER. At this size the dimensions
            do not fit and would be unreadable if they did - the tile is for
            recognising something, and the part screen is for reading about
            it. */}
        {shelf.length ? (
          <View style={styles.block}>
            <View style={styles.blockHead}>
              <Mono size="micro" color={core.dim} style={styles.grow}>
                {shelf.length === 1 ? 'the last thing you made' : 'what you have made'}
              </Mono>
              <Quiet label="see all" color={core.phosphor} onPress={onSeeAll} />
            </View>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.shelf}>
              {shelf.map((part) => (
                <Press key={part.dir} onPress={() => onPart(part.dir)}>
                  <Surface step="card" flat style={styles.shelfTile}>
                    {part.built ? (
                      <Image
                        source={{ uri: api.frameUrl(part.dir, THUMB_STEP, 320) }}
                        style={styles.shelfThumb}
                        resizeMode="contain"
                      />
                    ) : (
                      <View style={[styles.shelfThumb, styles.noThumb]}>
                        <Mono size="micro" color={pen.warn}>
                          no mesh
                        </Mono>
                      </View>
                    )}
                    <Mono size="micro" numberOfLines={1} style={styles.shelfName}>
                      {part.name}
                    </Mono>
                  </Surface>
                </Press>
              ))}
            </ScrollView>
          </View>
        ) : null}

        {/* A FIRST LAUNCH HAS NOTHING TO SHOW AND SHOULD SAY SO ONCE, quietly,
            rather than leaving the bottom of the screen simply empty. */}
        {ready && parts !== null && parts.length === 0 && !running.length ? (
          <Prose size="body" color={core.dim}>
            Nothing made yet. Whatever you describe gets built on your computer, measured, and
            checked against the printer above.
          </Prose>
        ) : null}

        {/* SETTINGS UNDER THE INPUT, SHUT. Meshy's are a collapsed column
            below the drop zone, and the reason is the same here: a first-time
            user should be able to ignore every one of them and still get a
            part. */}
        <Quiet
          label={more ? '– fewer options' : '+ more options'}
          onPress={() => setMore((m) => !m)}
        />

        {more ? (
          <Surface step="panel" style={styles.card}>
            {materials.length ? (
              <View style={styles.block}>
                <Mono size="micro" color={core.dim}>
                  material
                </Mono>
                <View style={styles.chips}>
                  {materials.map((name) => (
                    <Chip
                      key={name}
                      label={name}
                      active={name === chosen}
                      onPress={() => onMaterial(name)}
                    />
                  ))}
                </View>
                <Prose size="body" color={core.dim}>
                  These are the materials this machine's profile has. The choice is remembered.
                </Prose>
              </View>
            ) : null}

            <View style={styles.block}>
              <Mono size="micro" color={core.dim}>
                already have a model?
              </Mono>
              <Prose size="body" color={core.dim}>
                An STL, OBJ, PLY or glTF - anything off Printables, Thingiverse or Meshy. whittle
                reads it, repairs what it can, says what it cannot, and gives you sliders.
              </Prose>
              <Button label="open a file" onPress={openFile} disabled={!ready} />
            </View>
          </Surface>
        ) : null}

        {/* THE PRIVACY LINE, ALSO ONCE. It is worth saying and it is worth
            saying early - but it answers a question somebody asks on their
            first visit, and after that it is two lines of furniture at the
            bottom of every session. It is on the machine tab in full, beside
            the address that makes it true. */}
        {firstTime ? (
          <Prose size="body" color={core.dim} style={styles.footNote}>
            Nothing is uploaded anywhere - it is built on your own computer.
          </Prose>
        ) : null}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}


/**
 * What the engine actually read off the picture, and the one thing it needs
 * from a person to turn it into millimetres.
 *
 * THE APP WAS THROWING THIS AWAY. `/api/upload` measures the image the moment
 * it lands - silhouette extent, the largest neutral region, the aspect - and
 * returns every figure. The screen showed "photo: ref-1757.jpg" and a warning
 * that said, in effect, that measurements existed somewhere.
 *
 * A PHOTO GIVES SHAPE, NOT SIZE, and that is not a caveat to apologise for -
 * it is the whole of what is missing and it is one number. The silhouette is
 * 638 x 684 px, so the aspect is fixed; say the object is 150 mm across and
 * every other dimension follows from a measurement rather than a guess. Rule
 * 13 is that any dimension derived from an image comes from `measure/` and not
 * from an eyeball read, and this is the step where a person supplies the one
 * thing no image contains.
 *
 * So it shows the figures, takes one real measurement, works the other out,
 * and writes both into the sentence - where the engine will read them.
 */
function FromPhoto({
  photo,
  onRemove,
  onScale,
}: {
  photo: UploadedImage;
  onRemove: () => void;
  onScale: (sentence: string) => void;
}) {
  const [across, setAcross] = useState('');

  const wide = Number(photo.measured?.width_px);
  const tall = Number(photo.measured?.height_px);
  const measured = Number.isFinite(wide) && Number.isFinite(tall) && tall > 0;

  const real = Number(across);
  const ready = measured && Number.isFinite(real) && real > 0;
  // THE OTHER DIMENSION, FROM THE MEASURED ASPECT. Not a guess and not a
  // round number: it is the height the picture actually has, at the width the
  // person actually measured.
  const impliedTall = ready ? (real * tall) / wide : null;

  return (
    <View style={styles.photo}>
      <View style={styles.photoRow}>
        <Mono size="micro" color={core.dim} numberOfLines={1} style={styles.grow}>
          photo: {photo.name}
        </Mono>
        <Quiet label="remove" color={core.phosphor} onPress={onRemove} />
      </View>

      {measured ? (
        <>
          <Mono size="micro" color={core.dim}>
            measured {Math.round(wide)} × {Math.round(tall)} px from the background
          </Mono>
          {/* ONE NUMBER, AND THE REST IS ARITHMETIC. Asking for "the
              dimensions" would be asking a person to measure something the
              picture already fixes. */}
          <View style={styles.scaleRow}>
            <Mono size="label" color={core.dim}>
              it is
            </Mono>
            <Surface step="well" style={styles.scaleWell}>
              <TextInput
                value={across}
                onChangeText={setAcross}
                keyboardType="numeric"
                placeholder="150"
                placeholderTextColor={core.dim}
                style={styles.scaleInput}
              />
            </Surface>
            <Mono size="label" color={core.dim}>
              mm across
            </Mono>
          </View>
          {impliedTall !== null ? (
            <Verdict
              state="pass"
              text={`then it is ${impliedTall.toFixed(0)} mm tall - measured off the photo, not guessed`}
            />
          ) : null}
          <Button
            label="use these measurements"
            onPress={() =>
              onScale(
                `${real.toFixed(0)}mm wide and ${impliedTall!.toFixed(0)}mm tall, like the photo`,
              )
            }
            disabled={!ready}
          />
        </>
      ) : (
        <Verdict
          state="warn"
          text={
            photo.note ||
            'nothing separated from the background, so there is nothing measured to scale - say the size in words instead'
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
  },
  centre: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.base,
  },
  middle: {
    textAlign: 'center',
    marginTop: space.base,
  },
  body: {
    padding: space.base,
    gap: space.base,
    paddingBottom: space.room,
  },
  brandRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
    paddingTop: space.snug,
  },
  mark: {
    // TRIMMED TO ITS INK - see `_trim` in build_brand.py. This was the ANDROID
    // LAUNCHER foreground, which carries a 72 dp safe zone by design, so a
    // third of it was transparent margin: the mark drew two thirds the size it
    // was asked for and pushed the wordmark a third of its width away.
    height: 26,
    width: 26 * (166 / 164),
  },
  wordmark: {
    // TRIMMED TO ITS INK, so these are the letters and nothing else - see
    // `_trim` in build_brand.py. Sized by its own aspect: a logotype squashed
    // to fit a box is a logotype nobody may use.
    //
    // 17 rather than the mark's 26, because the mark is a full-height object
    // and this is lowercase with no ascender above the `h` and `l`. Matching
    // the two numbers makes the word tower over the mark.
    height: 17,
    width: 17 * (319 / 71),
  },
  state: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.tight,
    minHeight: metric.tap - space.base,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  hero: {
    paddingTop: space.snug,
    paddingBottom: space.tight,
  },
  offline: {
    padding: space.base,
    gap: space.snug,
  },
  composer: {
    padding: space.base,
    gap: space.snug,
  },
  composerFocused: {
    // THE FOCUS RING IS THE BORDER, and on a hairline it is nearly invisible.
    // A focused composer is the one moment this screen has a single obvious
    // subject, so the ring is a real line rather than a suggestion of one.
    borderWidth: 1.5,
  },
  prompt: {
    // THREE LINES OF ROOM, NOT FOUR-AND-A-BIT. At tap*1.6 the box held a
    // one-line placeholder over a visible void, which reads as something that
    // failed to load rather than as room to write in. This is enough for the
    // sentences people actually type - "a bracket for a 35 mm pipe, 4 mm
    // thick" wraps to two - and it still grows as you go past it.
    minHeight: type.size.reading * 1.4 * 3,
    color: core.screen,
    fontFamily: type.mono,
    fontSize: type.size.reading,
    lineHeight: type.size.reading * 1.4,
    textAlignVertical: 'top',
    padding: 0,
  },
  rule: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: glass.hairline(),
  },
  photo: {
    gap: space.snug,
  },
  photoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  scaleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  scaleWell: {
    paddingHorizontal: space.snug,
    minWidth: 84,
  },
  scaleInput: {
    minHeight: metric.tap,
    color: core.screen,
    fontFamily: type.mono,
    fontSize: type.size.body,
    padding: 0,
  },
  actions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  profile: {
    gap: space.hair,
    paddingLeft: space.snug,
    borderLeftWidth: 2,
    borderLeftColor: core.phosphor,
  },
  profileLine: {
    lineHeight: type.size.label * 1.5,
  },
  block: {
    gap: space.snug,
  },
  blockHead: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  examples: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.tight,
  },
  job: {
    padding: space.base,
    gap: space.tight,
  },
  jobHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  noThumb: {
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: pen.warn,
  },
  card: {
    padding: space.base,
    gap: space.snug,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.tight,
  },
  grow: {
    flex: 1,
  },
  shelf: {
    gap: space.snug,
    paddingRight: space.base,
  },
  shelfTile: {
    width: 116,
    padding: space.tight,
    gap: space.hair,
  },
  shelfThumb: {
    // 0.78 AS TALL AS IT IS WIDE, which is the ratio the server renders
    // every turntable frame at - carried over from the card this replaced,
    // where it was already written down. A tile at any other ratio
    // letterboxes the picture and wastes the space it was given.
    width: '100%',
    height: Math.round(116 * 0.78),
    borderRadius: radius.control,
  },
  shelfName: {
    paddingHorizontal: space.hair,
  },
  footNote: {
    paddingTop: space.snug,
  },
});
