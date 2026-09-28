/**
 * One object, one loop, whatever it came from.
 *
 * THE PROBLEM THIS SOLVES, WHICH WAS AN INTERFACE PROBLEM AND NOT AN ENGINE ONE
 * ----------------------------------------------------------------------------
 * whittle has two ways in - describe a part and the engine builds it, or bring
 * a mesh and work on it - and the engine treats them as equals. The app did
 * not. It had two screens:
 *
 *   Part.tsx    change it | checks | measured | report     a built part
 *   Edit.tsx    model | edits | checks | save              an imported mesh
 *
 * Two names for the same tab three times over, and one thing that was not a
 * naming difference at all: the part screen drew its sentence box inside
 * `{!imported ? ... : null}`. Bring a model in and there was NOWHERE TO SAY
 * ANYTHING TO IT. The sliders were on the other screen, behind a button.
 *
 * Both halves already existed on the server - `refine` for a part with a spec
 * behind it, `say` for a project - so the split was the app's alone.
 *
 * WHAT THIS MODULE IS
 * -------------------
 * The part of "one workbench" that is logic rather than layout: which way a
 * sentence goes, and how either origin's verdict becomes the SAME one line.
 * Kept out of the component so it can be tested without a renderer, which is
 * the only way any of this gets checked at all - there is no way to look at a
 * phone screen from here.
 *
 * WHY THE VERDICT IS ONE LINE AND NOT A TAB
 * -----------------------------------------
 * "always printable" is the promise the product makes. A promise you have to
 * navigate to is a promise you check once and then stop checking. It belongs
 * on screen at all times, next to the thing it is about, and it has to say the
 * same thing about a mesh as about a part or it is two promises.
 */

import type { Api, BuiltPart, Checks, Project, Report, Said } from './api';

// ---------------------------------------------------------------------------
// where the object came from
// ---------------------------------------------------------------------------

/**
 * The two origins, and the only thing the workbench needs to know about them.
 *
 * A DISCRIMINATED UNION RATHER THAN A BOOLEAN. `imported: true` was the old
 * shape and it answers "is this an import" while the question the screen keeps
 * asking is "where does this sentence go" - which needs the id, not the flag.
 * Every place that branched on the boolean had to go and find the id again.
 */
export type Origin =
  | { kind: 'part'; name: string }
  | { kind: 'project'; id: string };

/** The tone of a standing line, which is also what colours it. */
export type Tone = 'pass' | 'warn' | 'fail' | 'unknown';

/**
 * The one line that is always on screen: does it print, and how big is it.
 *
 * `detail` is the single most useful further fact, never a list. A line that
 * grows to three problems is a panel, and there is a panel for that.
 */
export interface Standing {
  tone: Tone;
  headline: string;
  detail: string;
  /** True when the geometry has moved and the verdict has not caught up. */
  stale: boolean;
}

// ---------------------------------------------------------------------------
// the verdict, from either origin, in the same words
// ---------------------------------------------------------------------------

/** "128 × 92 × 70 mm", or nothing when no size is known. */
export function sizeLine(size: number[] | null | undefined): string {
  if (!size || size.length < 3) return '';
  return size.slice(0, 3).map((n) => Math.round(n)).join(' × ') + ' mm';
}

function volumeLine(volume: number | null | undefined): string {
  if (volume === null || volume === undefined || !(volume > 0)) return '';
  return volume >= 100 ? `${Math.round(volume)} cm³` : `${volume.toFixed(1)} cm³`;
}

/** The facts under the headline, joined - size, volume, pieces. */
function facts(parts: (string | null | undefined)[]): string {
  return parts.filter((p): p is string => Boolean(p)).join('  ·  ');
}

/**
 * A built part's standing, off its stored checks or its build result.
 *
 * THE VERDICT WORD IS THE ENGINE'S. It is not re-derived here from `ok`,
 * because the engine distinguishes states this screen has no business
 * collapsing - a part that verified, a part that verified against a printer
 * profile that has since moved, and a part that never built are three
 * different things and only one of them is "no".
 */
export function standingOfPart(
  detail: { size_mm?: number[]; volume_cm3?: number; bodies?: number; checks?: Checks } | null,
  fresh?: BuiltPart | null,
): Standing {
  const checks = detail?.checks;
  const size = sizeLine(fresh?.size_mm ?? detail?.size_mm);
  const volume = volumeLine(fresh?.volume_cm3 ?? detail?.volume_cm3);
  const bodies = fresh?.bodies ?? detail?.bodies;
  const pieces = bodies && bodies > 1 ? `${bodies} pieces` : '';
  const detailLine = facts([size, volume, pieces]);

  if (!checks && !fresh) {
    return { tone: 'unknown', headline: 'not checked yet', detail: detailLine, stale: false };
  }

  const ok = checks ? checks.ok : Boolean(fresh?.ok);
  const problems = checks?.problems ?? fresh?.problems ?? [];
  const warnings = checks?.warnings ?? fresh?.warnings ?? [];
  const drift = checks?.drift ?? [];

  if (!ok) {
    return {
      tone: 'fail',
      headline: 'will not print as it is',
      // THE FIRST PROBLEM, IN THE ENGINE'S OWN WORDS. An apology written here
      // would be worse than "545 mm2 of underside overhangs past 45 degrees".
      detail: problems[0] ?? detailLine,
      stale: false,
    };
  }
  if (drift.length) {
    return {
      tone: 'warn',
      headline: 'prints, but the verdict is old',
      detail: drift[0],
      stale: true,
    };
  }
  if (warnings.length) {
    return { tone: 'warn', headline: 'prints, with a caveat', detail: warnings[0], stale: false };
  }
  return { tone: 'pass', headline: 'prints', detail: detailLine, stale: false };
}

/**
 * An imported mesh's standing, off its report.
 *
 * SAME WORDS AS A PART. "prints" has to mean the same thing on a mesh as on a
 * design or the line is decoration. The only honest difference is `stale`,
 * which a mesh really does have and a part does not: the server skips the
 * printability gate while a slider is mid-drag, because checking it costs
 * 488 ms a move against 43 ms for the geometry alone.
 */
export function standingOfProject(project: Project | null): Standing {
  if (!project) {
    return { tone: 'unknown', headline: 'nothing open', detail: '', stale: false };
  }
  const report: Report | undefined = project.report;
  const detailLine = facts([
    sizeLine(project.size_mm),
    project.bodies > 1 ? `${project.bodies} pieces` : '',
    project.triangles ? `${project.triangles.toLocaleString()} triangles` : '',
  ]);

  if (!report) {
    return { tone: 'unknown', headline: 'not checked yet', detail: detailLine, stale: false };
  }
  if (report.stale) {
    return { tone: 'warn', headline: 'checking…', detail: detailLine, stale: true };
  }
  if (!report.printable) {
    const worst =
      report.findings.find((f) => f.severity === 'fail') ?? report.findings[0];
    return {
      tone: 'fail',
      headline: 'will not print as it is',
      detail: worst ? worst.detail : detailLine,
      stale: false,
    };
  }
  const warn = report.findings.find((f) => f.severity === 'warn');
  if (warn) {
    return { tone: 'warn', headline: 'prints, with a caveat', detail: warn.detail, stale: false };
  }
  return { tone: 'pass', headline: 'prints', detail: detailLine, stale: false };
}

// ---------------------------------------------------------------------------
// saying the next thing
// ---------------------------------------------------------------------------

/**
 * What came back from saying something. One shape for both origins, because
 * the screen does the same thing with it either way: show what was understood,
 * say out loud what was not, and draw the new object.
 */
export type Reply =
  | { at: 'part'; jobId: string }
  | { at: 'project'; said: Said };

/**
 * Send a sentence to whichever half of the engine owns this object.
 *
 * THE BOX IS ALWAYS THERE AND THIS IS WHY IT CAN BE. Routing used to be the
 * screen's problem, so the screen solved it by not drawing the box on an
 * import - `/api/refine` answers "no part called x, or it has no spec.yaml to
 * change" for a mesh, and a box that always fails on the most prominent line
 * of the screen is worse than no box. It is one function's problem now, and it
 * cannot be got wrong: there is nowhere to pass a name for a project.
 */
export async function sayTo(api: Api, origin: Origin, sentence: string): Promise<Reply> {
  if (origin.kind === 'part') {
    const started = await api.refine(origin.name, sentence);
    return { at: 'part', jobId: started.job };
  }
  return { at: 'project', said: await api.say(origin.id, sentence) };
}

/**
 * The placeholder in the box, which is a promise about what it accepts.
 *
 * A MESH AND A DESIGN TAKE DIFFERENT SENTENCES and pretending otherwise is how
 * somebody types "make the wall 3 mm" at a mesh that has no wall. The examples
 * differ; the box does not.
 */
export function sayHint(origin: Origin, first?: string): string {
  if (first) return first;
  return origin.kind === 'part'
    ? 'say what to change'
    : 'hollow it, stand it flat, cut it to fit the bed';
}

// ---------------------------------------------------------------------------
// the drawer
// ---------------------------------------------------------------------------

/**
 * One set of words for both origins.
 *
 * The two screens had `change it | checks | measured | report` and
 * `model | edits | checks | save` - the same four things, named differently
 * three times out of four. These are the four, in the order somebody reaches
 * for them: the numbers they want to move, whether it prints, what it is, and
 * how to get it off the phone.
 */
export const PANELS = ['shape', 'prints', 'about', 'save'] as const;
export type PanelName = (typeof PANELS)[number];

/**
 * Which panel to open when the drawer is pulled up with nothing chosen.
 *
 * NOT ALWAYS THE FIRST ONE. If the object will not print, the thing somebody
 * wants is the reason - opening on the sliders makes them go and find it. A
 * working object opens on the numbers, because then the next move is a change
 * rather than a diagnosis.
 */
export function openAt(standing: Standing): PanelName {
  return standing.tone === 'fail' ? 'prints' : 'shape';
}
