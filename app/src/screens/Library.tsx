/**
 * Everything on this machine, as pictures, however many there are.
 *
 * MESHY'S ASSETS PANEL, WHICH IS THE HALF OF THEIR WORKSPACE THAT NEVER GOES
 * AWAY. Their generation history is always on screen, as thumbnails, with a
 * search over it. Ours was sixteen rows of text buried behind the third
 * segment of a control on the making screen, and a person looking for the
 * birdhouse they made yesterday had to read every row.
 *
 * WHAT CHANGED, AND WHY IT HAD TO
 * -------------------------------
 * The first version of this grid held the WHOLE library in memory, filtered it
 * in JavaScript on every keystroke, and drew a tile for every part at once.
 * That is correct at forty models. It is the wrong shape entirely for the
 * library this is now for - hundreds of STLs pulled off Printables,
 * Thingiverse and Creality Cloud - where the whole list crossing the wire on
 * every open is a slow screen, and a phone laying out four hundred tiles is a
 * slow one twice.
 *
 * So three things moved:
 *
 * * THE SEARCH RUNS ON THE ENGINE. It already owns one that matches a part's
 *   name, template, material, the prompt that made it and the filename it
 *   arrived as. Asking it is one short answer instead of the whole library
 *   plus a copy of its search written again in TypeScript.
 * * THE GRID IS VIRTUALISED. A FlatList draws the rows on screen and a little
 *   either side. Four hundred tiles cost what twelve cost.
 * * IT ARRIVES A PAGE AT A TIME, and the next page is fetched as the bottom
 *   comes near. Nothing is hidden by it - the count above the grid always says
 *   how many there are in total.
 *
 * AND IT HAS TO BE USABLE BY SOMEBODY WHO HAS NEVER SEEN IT. The controls are
 * one search box and one row of words with counts beside them. Sorting only
 * appears once there is enough here for the order to matter; a person with
 * three models does not need to be asked how to arrange them. Every word on
 * screen is the ordinary one: "made here", "brought in", "didn't finish" -
 * not "built", "imported", "draft".
 *
 * THIS SCREEN OWNS NO TIMER. The jobs list arrives as props from src/machine.ts
 * so that two tabs cannot disagree about what the engine is doing. What it
 * owns is the query, which is nobody else's business.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  StyleSheet,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';

import type { Api, LibraryAnswer, LibraryPart, MachineJob } from '../api';
import { core, metric, pen, radius, space, type } from '../tokens';
import { Chip, Empty, Mono, Problem, Prose, Quiet, Surface, Verdict } from '../ui';

/** The turntable step a thumbnail uses. Three-quarter view, like the mark. */
const THUMB_STEP = 3;

/**
 * How many tiles arrive at a time.
 *
 * Two columns, so this is thirty rows - several screens' worth, which means
 * scrolling normally never waits for the network, and a library of forty
 * still arrives in one answer.
 */
const PAGE = 60;

/**
 * How long the box waits after the last keystroke before asking.
 *
 * A REQUEST PER LETTER is how a search box becomes slower than no search box:
 * "birdhouse" is nine round trips, eight of which are thrown away, and on a
 * phone over adb the answers can land out of order. A quarter of a second is
 * under what reads as a pause and collapses a typed word into one question.
 */
const SETTLE_MS = 250;

/**
 * When the sorting controls are worth showing at all.
 *
 * A person with eight models does not need to be asked how to arrange them,
 * and every control on screen that does not earn its place is one more thing
 * to read before you can use the thing. Above this many, "which of these is
 * the big one" becomes a real question.
 */
const SORT_WORTH_OFFERING = 12;

/**
 * One tile's picture, with something to look at while it is being made.
 *
 * A COLD FRAME IS NOT FREE. The server caches every render it has made, so a
 * library that has been opened before draws instantly - but the ASSEMBLED
 * layout is rebuilt from the spec to render it, which is seconds of CAD the
 * first time, per part. This drew each one as an empty box until it arrived:
 * on a machine also running three builds, a screen of blank rectangles that
 * looks exactly like the thumbnails are broken.
 *
 * So there is a state before the picture, and a failed load says so rather
 * than staying blank for ever - that is a part whose render was never
 * written, which is a fact about the part and not about the network.
 */
function Thumb({ uri, height }: { uri: string; height: number }) {
  const [state, setState] = useState<'loading' | 'shown' | 'failed'>('loading');

  return (
    <View style={[styles.thumb, { height }]}>
      <Image
        source={{ uri }}
        style={[StyleSheet.absoluteFill, state === 'shown' ? null : styles.hidden]}
        resizeMode="contain"
        onLoad={() => setState('shown')}
        onError={() => setState('failed')}
      />
      {state !== 'shown' ? (
        <View style={styles.thumbWaiting}>
          <Mono size="micro" color={core.dim} numberOfLines={2} style={styles.thumbWord}>
            {state === 'loading' ? 'drawing it…' : 'no picture'}
          </Mono>
        </View>
      ) : null}
    </View>
  );
}

/**
 * The four things somebody might want to see, in the words they would use.
 *
 * `key` is the engine's filter and `word` is what goes on screen. They differ
 * on purpose: "unfinished" is what the route calls a run that did not produce
 * a part, and "didn't finish" is what a person calls it.
 */
type Show = 'all' | 'made' | 'brought-in' | 'unfinished';
const SHOWS: { key: Show; word: string }[] = [
  { key: 'all', word: 'everything' },
  { key: 'made', word: 'made here' },
  { key: 'brought-in', word: 'brought in' },
  { key: 'unfinished', word: "didn't finish" },
];

type Sort = 'newest' | 'oldest' | 'name' | 'biggest' | 'smallest';
const SORTS: { key: Sort; word: string }[] = [
  { key: 'newest', word: 'newest' },
  { key: 'oldest', word: 'oldest' },
  { key: 'name', word: 'by name' },
  { key: 'biggest', word: 'biggest' },
];

interface Props {
  api: Api;
  ready: boolean;
  /**
   * The whole library, from the polling hook.
   *
   * NOT WHAT THE GRID DRAWS, and that is the point of the change: the grid
   * asks the engine its own question and draws the answer. This is here so
   * the grid can notice when a build finishes - the count moves, and the
   * current page is asked for again.
   */
  parts: LibraryPart[] | null;
  partsProblem: string | null;
  jobs: MachineJob[];
  onReload: () => Promise<void>;
  onPart: (dir: string) => void;
  /** Tapping a job that is still running goes and watches it. */
  onWatch: (jobId: string, request: string) => void;
  onFixConnection: () => void;
  /** Bring a mesh in from the phone's own files. */
  onImport: () => void;
}

export function LibraryScreen({
  api,
  ready,
  parts,
  partsProblem,
  jobs,
  onReload,
  onPart,
  onWatch,
  onFixConnection,
  onImport,
}: Props) {
  const [typed, setTyped] = useState('');
  const [query, setQuery] = useState('');
  const [show, setShow] = useState<Show>('all');
  const [sort, setSort] = useState<Sort>('newest');
  /**
   * One tile per thing, or one per build.
   *
   * COLLAPSED BY DEFAULT, because the ordinary workflow makes chains: four
   * tweaks to a birdhouse leave four verified parts, and four identical tiles
   * are four chances to open the wrong one. Nothing is hidden by it - the
   * count is on the tile, the part screen lists every build, and this turns
   * it off for anybody who would rather see the lot.
   *
   * The engine does the collapsing now. It has to: this screen holds a page,
   * not the library.
   */
  const [everyBuild, setEveryBuild] = useState(false);
  /**
   * One tag, or none.
   *
   * WHERE TAGS COME FROM: a file brought in carries them, so a library filled
   * from Printables, Thingiverse and Creality Cloud already knows which is
   * which. That makes "show me the Thingiverse ones" a tap rather than a
   * search, and it costs nothing to offer because the engine counts them
   * anyway.
   *
   * ONE AT A TIME, on purpose. Two tags means explaining whether it is "and"
   * or "or" to somebody who came here to find a bracket.
   */
  const [tag, setTag] = useState<string | null>(null);
  /**
   * Whether the ordering controls are on screen.
   *
   * FOLDED AWAY BECAUSE OF WHAT IT LOOKED LIKE ON THE PHONE. Search, four
   * filter chips, four sort chips and a toggle wrapped onto four rows, and
   * the first model sat below the halfway line - on a screen whose entire
   * job is showing models. Every row of controls above the grid is a row
   * somebody has to read past to get to what they came for.
   *
   * The order is a question people ask occasionally; the filter is one they
   * ask constantly. So the filters stay out and the order is one tap away,
   * with the current choice named on the button so nothing is hidden.
   */
  const [sortOpen, setSortOpen] = useState(false);

  const [answer, setAnswer] = useState<LibraryAnswer | null>(null);
  const [rows, setRows] = useState<LibraryPart[]>([]);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const { width } = useWindowDimensions();
  // Two across, with the page's own padding and one gap taken off.
  const cell = (width - space.base * 2 - space.snug) / 2;

  /**
   * ONLY THE NEWEST ANSWER IS ALLOWED TO LAND.
   *
   * Typing "box" fires a request; so does deleting the x. Over a slow link
   * the first can arrive second, and the grid would show results for a query
   * nobody is looking at any more with no way to tell. Each request carries a
   * number and anything but the latest is dropped.
   */
  const latest = useRef(0);

  const ask = useCallback(
    async (cursor: string | null) => {
      const ticket = ++latest.current;
      if (cursor) setMore(true);
      else setLoading(true);
      try {
        const page = await api.libraryPage({
          q: query,
          show,
          sort,
          builds: everyBuild ? 'all' : 'latest',
          tag: tag ?? undefined,
          limit: PAGE,
          cursor: cursor ?? undefined,
        });
        if (ticket !== latest.current) return;
        setAnswer(page);
        setRows((held) => (cursor ? [...held, ...page.parts] : page.parts));
        setProblem(null);
      } catch (error: any) {
        if (ticket !== latest.current) return;
        setProblem(String(error?.message ?? error));
      } finally {
        if (ticket === latest.current) {
          setLoading(false);
          setMore(false);
        }
      }
    },
    [api, everyBuild, query, show, sort, tag],
  );

  // THE TYPING SETTLES BEFORE IT IS ASKED. See SETTLE_MS.
  useEffect(() => {
    const timer = setTimeout(() => setQuery(typed.trim()), SETTLE_MS);
    return () => clearTimeout(timer);
  }, [typed]);

  // A NEW QUESTION STARTS AT THE TOP. Changing the filter while holding page
  // four of the old answer would append unrelated tiles to it.
  useEffect(() => {
    if (ready) void ask(null);
  }, [ask, ready]);

  /**
   * WHEN A BUILD FINISHES, ASK AGAIN.
   *
   * The polling hook is the only thing that knows; without this a part you
   * just made does not appear until the tab is left and come back to, which
   * reads as the app having lost it.
   */
  const libraryCount = parts?.length ?? -1;
  useEffect(() => {
    if (ready && libraryCount >= 0) void ask(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [libraryCount]);

  const pull = useCallback(async () => {
    setRefreshing(true);
    await onReload();
    await ask(null);
    setRefreshing(false);
  }, [ask, onReload]);

  const reachedTheEnd = useCallback(() => {
    if (!more && !loading && answer?.next_cursor) void ask(answer.next_cursor);
  }, [answer, ask, loading, more]);

  const running = jobs.filter((job) => !job.done);
  const counts = answer?.facets.show;
  /**
   * The handful of tags worth putting on screen.
   *
   * The engine sends the top two dozen by count; a phone has room for a few.
   * A tag that is already chosen always stays, or choosing an uncommon one
   * would make its own chip disappear and leave no way to undo it.
   */
  const tags = useMemo(() => {
    const all = answer?.facets.tag ?? [];
    const top = all.slice(0, 6);
    if (tag && !top.some((one) => one.name === tag)) {
      const chosen = all.find((one) => one.name === tag);
      if (chosen) return [chosen, ...top.slice(0, 5)];
    }
    return top;
  }, [answer, tag]);
  const total = answer?.total ?? 0;
  const matched = answer?.matched ?? 0;
  const searching = Boolean(query) || show !== 'all' || Boolean(tag);

  /** The count for one chip, or undefined when the engine has not said yet. */
  const countFor = useCallback(
    (key: Show): number | undefined => {
      if (!counts) return undefined;
      if (key === 'all') return total;
      return counts[key];
    },
    [counts, total],
  );

  const header = useMemo(
    () => (
      <View style={styles.head}>
        <View style={styles.titleRow}>
          <Prose size="title" weight="bold" color={core.screen} style={styles.grow}>
            your models
          </Prose>
          {/* A FILE MANAGER NEEDS A WAY TO PUT A FILE IN IT, and it belongs
              where the files are rather than folded into another screen. */}
          <Quiet label="+ add an stl" color={core.phosphor} onPress={onImport} />
        </View>

        {/* HOW MANY THERE ARE, ALWAYS. With a search running this is the
            difference between "3 of 412" and a screen that looks like the
            library emptied itself. */}
        {answer ? (
          <View style={styles.countRow}>
            <Mono size="micro" color={core.dim} style={styles.grow}>
              {searching
                ? `${matched} of ${total}`
                : `${total} ${total === 1 ? 'model' : 'models'}`}
              {running.length ? `  ·  ${running.length} building` : ''}
            </Mono>
            {/* THE ORDER, NAMED, one tap from being changed. See sortOpen. */}
            {total > SORT_WORTH_OFFERING ? (
              <Quiet
                label={`${SORTS.find((one) => one.key === sort)?.word ?? sort} ${
                  sortOpen ? '▴' : '▾'
                }`}
                color={sortOpen ? core.phosphor : core.dim}
                onPress={() => setSortOpen((open) => !open)}
              />
            ) : null}
          </View>
        ) : null}

        {running.length ? (
          <View style={styles.block}>
            {running.map((job) => (
              <Pressable key={job.id} onPress={() => onWatch(job.id, job.request)}>
                <Surface step="well" style={styles.job}>
                  <Mono size="label" weight="medium" numberOfLines={1}>
                    {job.request || job.kind}
                  </Mono>
                  <Mono size="micro" color={core.dim} numberOfLines={1}>
                    {Math.round(job.elapsed_s)}s · {job.note || 'starting'}
                  </Mono>
                </Surface>
              </Pressable>
            ))}
          </View>
        ) : null}

        {problem ? <Problem text={problem} actionLabel="try again" onAction={pull} /> : null}
        {partsProblem && !problem ? (
          <Problem text={partsProblem} actionLabel="try again" onAction={pull} />
        ) : null}

        {/* THE SEARCH IS ALWAYS THERE once there is anything to search, and it
            is the first control on the screen because it is the one that
            answers the question this screen exists for. */}
        {total > 0 || query ? (
          <Surface step="well" style={styles.search}>
            <TextInput
              value={typed}
              onChangeText={setTyped}
              placeholder="search by name, or what you asked for"
              placeholderTextColor={core.dim}
              autoCapitalize="none"
              autoCorrect={false}
              returnKeyType="search"
              style={styles.searchInput}
            />
            {typed ? (
              <Pressable onPress={() => setTyped('')} hitSlop={12}>
                <Mono size="label" color={core.dim}>
                  ✕
                </Mono>
              </Pressable>
            ) : null}
          </Surface>
        ) : null}

        {/* ONE ROW OF WORDS WITH COUNTS. A chip that might turn out to be
            empty is a dead end; a chip that says how many are behind it is an
            offer. Anything with nothing behind it is not shown at all. */}
        {total > 0 ? (
          <View style={styles.chips}>
            {SHOWS.map(({ key, word }) => {
              const count = countFor(key);
              if (key !== 'all' && !count) return null;
              return (
                <Chip
                  key={key}
                  label={count === undefined ? word : `${word} ${count}`}
                  active={key === show}
                  onPress={() => setShow(key)}
                />
              );
            })}
          </View>
        ) : null}

        {/* WHERE THINGS CAME FROM, when anything says. Only shown once there
            are tags to show, so a library of parts made here never grows a
            row of controls that do nothing. */}
        {tags.length ? (
          <View style={styles.chips}>
            {tags.map((one) => (
              <Chip
                key={one.name}
                label={`${one.name} ${one.count}`}
                active={one.name === tag}
                onPress={() => setTag((held) => (held === one.name ? null : one.name))}
              />
            ))}
          </View>
        ) : null}

        {total > SORT_WORTH_OFFERING && sortOpen ? (
          <View style={styles.chips}>
            {SORTS.map(({ key, word }) => (
              <Chip key={key} label={word} active={key === sort} onPress={() => setSort(key)} />
            ))}
            {/* Only offered when something is actually collapsed behind it. A
                toggle that changes nothing teaches people the app does
                nothing. */}
            {everyBuild || rows.some((part) => (part.builds ?? 1) > 1) ? (
              <Chip
                label={everyBuild ? 'every build' : 'latest only'}
                active={everyBuild}
                onPress={() => setEveryBuild((v) => !v)}
              />
            ) : null}
          </View>
        ) : null}

        {loading && rows.length === 0 ? (
          <View style={styles.centre}>
            <ActivityIndicator color={core.dim} />
          </View>
        ) : null}

        {!loading && total === 0 && !query ? (
          <Empty
            title="nothing here yet"
            hint="Describe something on the make tab, or add an STL you already print - both land here."
          />
        ) : null}

        {!loading && matched === 0 && total > 0 ? (
          <Empty
            title="nothing matches that"
            hint="Clear the search, or tap everything to see all of them again."
          />
        ) : null}
      </View>
    ),
    [
      answer,
      countFor,
      loading,
      matched,
      onImport,
      onWatch,
      partsProblem,
      problem,
      pull,
      query,
      everyBuild,
      rows,
      running,
      searching,
      show,
      sort,
      sortOpen,
      tag,
      tags,
      total,
      typed,
    ],
  );

  if (!ready) {
    return (
      <View style={styles.body}>
        <Empty
          title="nothing to show until the machine answers"
          hint="The library is read off the computer running whittle."
        />
        <Pressable onPress={onFixConnection}>
          <Surface step="well" style={styles.link}>
            <Mono size="label" color={core.phosphor}>
              set the connection up ›
            </Mono>
          </Surface>
        </Pressable>
      </View>
    );
  }

  return (
    <FlatList
      data={rows}
      keyExtractor={(part) => part.dir}
      numColumns={2}
      columnWrapperStyle={styles.row}
      contentContainerStyle={styles.body}
      keyboardShouldPersistTaps="handled"
      ListHeaderComponent={header}
      // THE WHOLE REASON THIS IS A FlatList. Hundreds of tiles cost what a
      // dozen cost, because only the ones near the screen exist.
      initialNumToRender={8}
      windowSize={5}
      removeClippedSubviews
      onEndReached={reachedTheEnd}
      onEndReachedThreshold={0.6}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={pull} tintColor={core.dim} />
      }
      ListFooterComponent={
        <View style={styles.footer}>
          {more ? <ActivityIndicator color={core.dim} /> : null}
          {!more && answer && !answer.next_cursor && rows.length > 0 ? (
            <Mono size="micro" color={core.dim}>
              {rows.length === total
                ? 'that is all of them'
                : `${rows.length} of ${matched} shown`}
            </Mono>
          ) : null}
        </View>
      }
      renderItem={({ item: part }) => (
        <Pressable onPress={() => onPart(part.dir)} style={{ width: cell }}>
          {/* FLAT IN THE GRID. A blur is a live read of everything behind
              the view, and a scrolling grid of forty tiles is forty of them
              recomputed every frame. A gallery that stutters is worse than
              one whose tiles are a shade flatter - and this is the one
              screen in the app with that many surfaces at once. */}
          <Surface step="card" flat style={styles.tile}>
            {/* A PART THAT NEVER BUILT HAS NOTHING TO RENDER, and asking for a
                frame of it returns a 404 that React Native draws as an empty
                box. Four blank tiles in a row looks like the thumbnails are
                broken rather than like four that did not finish. */}
            {part.built ? (
              <Thumb uri={api.frameUrl(part.dir, THUMB_STEP, 320)} height={cell * 0.78} />
            ) : (
              <View style={[styles.thumb, styles.noThumb, { height: cell * 0.78 }]}>
                <Verdict state="warn" text="didn't finish" />
              </View>
            )}
            <View style={styles.tileHead}>
              <Mono size="label" weight="medium" numberOfLines={1} style={styles.grow}>
                {part.name}
              </Mono>
              {/* HOW MANY BUILDS THIS TILE STANDS FOR. Without it a collapsed
                  chain looks like the only one there ever was. */}
              {(part.builds ?? 1) > 1 ? (
                <Mono size="micro" color={core.phosphor}>
                  {part.builds}
                </Mono>
              ) : null}
            </View>
            {part.size_mm ? (
              <Mono size="micro" color={core.dim} numberOfLines={1}>
                {part.size_mm.map((v) => Math.round(v)).join(' × ')} mm
                {part.bodies && part.bodies > 1 ? `  ·  ${part.bodies} pieces` : ''}
              </Mono>
            ) : null}
            {/* WHAT KIND OF THING THIS IS. An import cannot be changed by
                describing the change, so somebody needs to know before they
                open it and try - and the file's own name is what they
                recognise, not the directory this program gave it. */}
            {part.origin === 'imported' ? (
              <Mono size="micro" color={pen.ref} numberOfLines={1}>
                {part.source_name || 'brought in'}
              </Mono>
            ) : part.material ? (
              <Mono size="micro" color={core.dim} numberOfLines={1}>
                {part.material}
              </Mono>
            ) : null}
          </Surface>
        </Pressable>
      )}
    />
  );
}

const styles = StyleSheet.create({
  body: {
    padding: space.base,
    gap: space.snug,
    paddingBottom: space.room,
  },
  head: {
    gap: space.snug,
    marginBottom: space.tight,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  grow: {
    flex: 1,
  },
  countRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
  },
  tileHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.tight,
  },
  centre: {
    alignItems: 'center',
    paddingVertical: space.loose,
  },
  block: {
    gap: space.snug,
  },
  job: {
    padding: space.snug,
    gap: space.hair,
  },
  link: {
    padding: space.base,
    alignItems: 'center',
  },
  search: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
    paddingHorizontal: space.snug,
  },
  searchInput: {
    flex: 1,
    minHeight: metric.tap,
    color: core.screen,
    fontFamily: type.mono,
    fontSize: type.size.body,
    padding: 0,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.tight,
  },
  row: {
    gap: space.snug,
    marginBottom: space.snug,
  },
  footer: {
    alignItems: 'center',
    paddingVertical: space.base,
    gap: space.snug,
  },
  tile: {
    padding: space.snug,
    gap: space.hair,
  },
  thumb: {
    width: '100%',
    borderRadius: radius.panel,
    overflow: 'hidden',
  },
  hidden: {
    opacity: 0,
  },
  thumbWaiting: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: 'center',
    justifyContent: 'center',
  },
  thumbWord: {
    textAlign: 'center',
  },
  noThumb: {
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: pen.warn,
    borderRadius: radius.panel,
  },
});
