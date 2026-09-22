/**
 * What the machine is, what it is doing, and what it has made - in one place.
 *
 * WHY THIS IS A HOOK AND NOT THREE useEffects ON THREE SCREENS. The landing
 * screen, the library and the machine screen all need some of this, and three
 * copies of the polling would disagree with each other the moment one of them
 * was on a screen that was not mounted. Worse, they would each hold their own
 * answer to "is it connected", so the make button could be disabled on one tab
 * while another showed a green dot.
 *
 * So it is fetched once, at the top of the app, and passed down. The screens
 * below are given data and callbacks; none of them owns a timer.
 *
 * THREE DIFFERENT CLOCKS, ON PURPOSE
 * ----------------------------------
 *   health   every 15s. The machine is a laptop that gets closed, and an app
 *            that asked once shows "connected" over a dead socket until
 *            something else fails. /api/health is a config read.
 *   jobs     every 2.5s while connected. This is an in-memory list on the
 *            server, and it is what makes "you can leave it running" visible.
 *   parts    on connect, and again when a running job finishes. A part appears
 *            in the library exactly once; re-reading the whole library every
 *            two seconds to notice that would be work on the server for a
 *            change the job list has already reported.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import type { Api, Health, LibraryPart, MachineJob, Usage } from './api';

const HEALTH_EVERY_MS = 15000;
const JOBS_EVERY_MS = 2500;

export interface Machine {
  /** Null whenever the last health call failed: this IS "not connected". */
  health: Health | null;
  /** True only before the first answer, so a first launch does not flash "offline". */
  checking: boolean;
  /** Why the last health call failed, in the server's or the network's words. */
  problem: string | null;
  jobs: MachineJob[];
  /** Null until the first read completes; [] is a machine with nothing made. */
  parts: LibraryPart[] | null;
  /** Why reading the library failed, which is a different fault to being offline. */
  partsProblem: string | null;
  /**
   * What this machine has spent. Null until the first read.
   *
   * Read on the same clock as the library rather than polled: it is a sum over
   * run.json files, which change when a build finishes - exactly when the
   * library is re-read anyway.
   */
  usage: Usage | null;
  /** Ask everything again, now. */
  refresh: () => void;
  /** Re-read the library only - what a pull-to-refresh does. */
  reloadParts: () => Promise<void>;
}

export function useMachine(api: Api, enabled: boolean): Machine {
  const [health, setHealth] = useState<Health | null>(null);
  const [checking, setChecking] = useState(true);
  const [problem, setProblem] = useState<string | null>(null);
  const [jobs, setJobs] = useState<MachineJob[]>([]);
  const [parts, setParts] = useState<LibraryPart[] | null>(null);
  const [partsProblem, setPartsProblem] = useState<string | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [asked, setAsked] = useState(0);

  const connected = Boolean(health);

  const reloadParts = useCallback(async () => {
    try {
      const { parts: found } = await api.parts();
      setParts(found);
      setPartsProblem(null);
    } catch (error: any) {
      setPartsProblem(String(error?.message ?? error));
    }
    // ON THE SAME CLOCK, NOT ITS OWN. Usage is a sum over run.json, which
    // changes exactly when a build finishes - which is exactly when the
    // library is re-read. A second timer would ask the same question twice.
    // An engine one version behind has no /api/usage, and a screen with no
    // figures is better than a screen that says the machine is broken.
    try {
      setUsage(await api.usage());
    } catch {
      setUsage(null);
    }
  }, [api]);

  // -- health --------------------------------------------------------------

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;

    const ask = async () => {
      if (!live) return;
      try {
        const found = await api.health();
        if (!live) return;
        setHealth(found);
        setProblem(null);
      } catch (error: any) {
        if (!live) return;
        setHealth(null);
        setProblem(String(error?.message ?? error));
      } finally {
        if (live) setChecking(false);
      }
      timer = setTimeout(ask, HEALTH_EVERY_MS);
    };

    setChecking(true);
    ask();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [api, enabled, asked]);

  // -- the library ---------------------------------------------------------

  // READ WHEN THE MACHINE COMES BACK, not on mount. On mount there is no
  // connection yet and the call fails, which used to leave the library showing
  // its own error next to a header that said "connected" ten seconds later.
  useEffect(() => {
    if (!connected) {
      setParts(null);
      setPartsProblem(null);
      setUsage(null);
      return;
    }
    reloadParts();
  }, [connected, reloadParts, asked]);

  // -- what it is doing ----------------------------------------------------

  // The running count from the previous tick lives in a ref rather than in
  // state: comparing it is what triggers the library re-read, and putting it
  // in state would re-run this effect and restart the timer every tick.
  const runningBefore = useRef(0);

  useEffect(() => {
    if (!enabled || !connected) {
      setJobs([]);
      runningBefore.current = 0;
      return;
    }
    let live = true;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      if (!live) return;
      try {
        const { jobs: found } = await api.jobs();
        if (!live) return;
        setJobs(found);
        const running = found.filter((job) => !job.done).length;
        // A JOB THAT FINISHED IS A PART THAT MAY HAVE APPEARED. This is the
        // whole reason the library does not poll: one re-read at the moment
        // something completes, instead of one every two seconds for ever.
        if (running < runningBefore.current) reloadParts();
        runningBefore.current = running;
      } catch {
        // A dropped poll is not a dropped build. Ask again.
      }
      timer = setTimeout(poll, JOBS_EVERY_MS);
    };

    poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [api, enabled, connected, reloadParts]);

  const refresh = useCallback(() => setAsked((n) => n + 1), []);

  return {
    health,
    checking,
    problem,
    jobs,
    parts,
    partsProblem,
    usage,
    refresh,
    reloadParts,
  };
}

/**
 * What a request made right now will be measured against, as one line.
 *
 * THIS IS THE SENTENCE MESHY CANNOT WRITE, and it is the reason it earns the
 * best line on the landing screen. Their generator does not know what you are
 * going to print with; every verdict this engine gives is measured against a
 * real nozzle, a real bed and a real material, and saying so BEFORE a request
 * is made is the difference between a toy and a tool.
 *
 * RULE 29 RUNS THROUGH IT. A value that has no measured source is the string
 * "UNSET" in the config and it is served that way, so a field that is not set
 * is dropped from the line rather than filled in with something plausible.
 */
export function measuredAgainst(health: Health | null, material: string | null): string[] {
  if (!health) return [];
  const bits: string[] = [];

  const printer = health.printer as Record<string, unknown> | undefined;
  const name = printer?.name;
  if (typeof name === 'string' && name && name !== 'UNSET') bits.push(name);

  const bed = health.bed as Record<string, unknown> | undefined;
  const w = numeric(bed?.width_mm);
  const d = numeric(bed?.depth_mm);
  const h = numeric(bed?.height_mm);
  if (w !== null && d !== null && h !== null) {
    bits.push(`${trim(w)} × ${trim(d)} × ${trim(h)} mm bed`);
  }

  const settings = (health as { print?: Record<string, unknown> }).print;
  const nozzle = numeric(settings?.nozzle_mm);
  if (nozzle !== null) bits.push(`${trim(nozzle)} mm nozzle`);

  // THE SERVER'S OWN DEFAULT, NOT THE HEAD OF A SORTED LIST. See
  // Health.material_default: picking materials[0] meant the line said "asa"
  // while the engine built in PETG. An engine that does not publish its
  // default gets no material named here at all - a missing word is better
  // than a wrong one, and this whole line exists to be trusted.
  const chosen = material ?? health.material_default;
  if (chosen) bits.push(chosen);

  return bits;
}

/**
 * Hold one phrase together when the line it is on wraps.
 *
 * The profile line has four items and a phone is narrow, so it wraps - and it
 * was breaking INSIDE them: "0.4 mm" on one row and "nozzle" on the next,
 * which reads for a moment as two separate facts. A measurement, its unit and
 * the thing it measures are one phrase.
 *
 * SEPARATE FROM `measuredAgainst`, which returns plain strings. Putting the
 * non-breaking spaces in there made every test assert on characters nobody can
 * see, and a test whose expected value is indistinguishable from the wrong
 * answer is not a test. This is the presentation half and it is applied where
 * the line is drawn.
 */
export function nowrap(text: string): string {
  return text.replace(/ /g, '\u00a0');
}

function numeric(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return null;
}

/** 260 rather than 260.0, 0.4 rather than 0.40 - without inventing digits. */
function trim(value: number): string {
  return String(Number(value.toFixed(2)));
}
