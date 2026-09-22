/**
 * The words that change a part, and which of them this part will understand.
 *
 * THE WORKFLOW THIS EXISTS FOR
 * ----------------------------
 * Somebody types "a bracket". They give no dimensions, because people do not
 * give dimensions to start with - they describe a thing. The engine builds a
 * good one, choosing what it was not told and marking every choice as an
 * assumption. Then the part is changed until it is right, by saying so or by
 * moving a slider, and that second half is the product as much as the first.
 *
 * So the change box needs a starting point. An empty field labelled "say what
 * to change" is the same failure as an empty field labelled "describe a part":
 * it works for somebody who already knows what the parser accepts.
 *
 * EVERY WORD HERE COMES FROM whittle/spec/language.py
 * ---------------------------------------------------
 * COMPARATIVES and OVERALL in that file are the vocabulary, and they are not
 * a prompt - they are a deterministic parser, which is why "make it taller"
 * takes a second and never depends on a 7B model having a good day. Inventing
 * a phrasing here that the parser does not read would produce a suggestion
 * that fails, which is worse than no suggestion.
 *
 * AND A WORD IS ONLY OFFERED IF THIS PART HAS THAT DIMENSION. The parser
 * matches an axis against the template's own field names and refuses "wider"
 * on a template with no width, rather than moving whatever field sorts first.
 * `available` mirrors that matching - see `_field_ending` in language.py - so
 * the app never offers a change the engine will decline.
 */

import type { Catalogue, ServedDimension, TemplateInfo } from './api';

/**
 * An axis, the words that move it, and the field suffix it is found by.
 *
 * The axis names are FIELD SUFFIXES matched against the schema: "height" finds
 * height_mm on any template that has one, and finds nothing on one that does
 * not.
 */
interface Axis {
  axis: string;
  up: string;
  down: string;
}

const AXES: Axis[] = [
  { axis: 'height', up: 'taller', down: 'shorter' },
  { axis: 'width', up: 'wider', down: 'narrower' },
  { axis: 'depth', up: 'deeper', down: 'shallower' },
  { axis: 'wall', up: 'thicker', down: 'thinner' },
];

/** "make it bigger" has no axis, so it takes every principal dimension. */
const PRINCIPAL = ['width', 'depth', 'height'];

export interface Tweak {
  /** The sentence that goes in the box, exactly as the parser reads it. */
  say: string;
  /** What it does, for anyone who has not read the parser. */
  note: string;
}

/**
 * Does this template have a numeric field for `axis`?
 *
 * Mirrors `_field_ending`: the exact name first, then any field that starts
 * with the axis and an underscore. Exact-ish rather than fuzzy, deliberately -
 * a loose match here would offer "wider" for `wire_width_mm` on a part whose
 * overall width is not adjustable at all.
 */
function hasAxis(params: TemplateInfo['params'], axis: string): boolean {
  const numeric = params.filter((p) => p.type === 'float' || p.type === 'int');
  return numeric.some(
    (p) => p.name === `${axis}_mm` || p.name === axis || p.name.startsWith(`${axis}_`),
  );
}

/**
 * The changes this part can actually be asked for, in the order people reach
 * for them.
 *
 * Returns [] when the template is unknown - an imported mesh, or an engine
 * that could not describe it. Offering the words anyway would be guessing at
 * what the part has, which is exactly what rule 9 forbids: the box still takes
 * any sentence, it simply gets no suggestions above it.
 */
export function tweaksFor(
  template: TemplateInfo | null,
  /**
   * What this part's spec currently holds, so a choice already in force is not
   * offered.
   *
   * THE SCHEMA DEFAULT IS NOT THE CURRENT VALUE. `roof_style` defaults to
   * "mono", and the birdhouse in this library is a gable - so filtering on the
   * default alone offers "make the roof gable" on a part that already has one,
   * which is a build that produces an identical part and a suggestion that
   * makes the app look like it did nothing.
   */
  current: Record<string, unknown> = {},
): Tweak[] {
  if (!template) return [];
  const out: Tweak[] = [];

  // OVERALL FIRST. "bigger" is what somebody says before they have decided
  // which dimension is wrong, and it is the commonest first change there is.
  if (PRINCIPAL.some((axis) => hasAxis(template.params, axis))) {
    out.push({ say: 'make it bigger', note: 'every dimension, by a quarter' });
    out.push({ say: 'make it smaller', note: 'every dimension, by a quarter' });
  }

  for (const { axis, up, down } of AXES) {
    if (!hasAxis(template.params, axis)) continue;
    out.push({ say: `make it ${up}`, note: axisNote(axis, true) });
    out.push({ say: `make it ${down}`, note: axisNote(axis, false) });
  }

  // THE CHOICES, WHICH ARE THE INTERESTING ONES. "Make this roof a triangular
  // roof" is the sentence rule 32 was written for, and a choice is the kind of
  // change nobody discovers by guessing - a person has to be told the part HAS
  // a roof style before they can ask for a different one.
  //
  // The value's own word is what goes in the sentence, because the parser
  // matches a choice by its value and by whatever synonyms the field declares.
  // A value already in force is not offered: changing something to what it
  // already is is a build that produces an identical part.
  for (const parameter of template.params) {
    if (!parameter.choices?.length) continue;
    const noun = readable(parameter.name);
    const inForce =
      parameter.name in current
        ? String(current[parameter.name])
        : String(parameter.default);
    for (const choice of parameter.choices) {
      if (inForce === choice) continue;
      out.push({
        say: `make the ${noun} ${choice}`,
        note: parameter.description || `${parameter.name} → ${choice}`,
      });
    }
  }

  // THE THINGS THAT ARE THERE OR NOT. `no roof`, `add a gusset` - the parser
  // reads `(no|without|remove|delete|drop) <word>` and
  // `(add|with|include|give it) <word>`, matched against the words in the
  // field's own name, so the phrasing here is those two prefixes and nothing
  // invented around them.
  //
  // Only the direction that changes something is offered: the parser skips a
  // change to the value already in force, so offering both would put a chip on
  // screen that does nothing when tapped.
  for (const parameter of template.params) {
    if (parameter.type !== 'bool') continue;
    const noun = readable(parameter.name);
    const on =
      parameter.name in current
        ? Boolean(current[parameter.name])
        : Boolean(parameter.default);
    out.push({
      say: on ? `no ${noun}` : `add a ${noun}`,
      note: parameter.description || (on ? `leave the ${noun} off` : `put a ${noun} on it`),
    });
  }

  return out;
}

/**
 * A field name as the noun a person would use for it.
 *
 * `roof_style` is "roof", `lid_style` is "lid". The trailing `_style` is the
 * schema's word for "which kind", and nobody says it out loud - which is
 * precisely rule 32's split between the parameter and the English.
 */
function readable(name: string): string {
  return name
    .replace(/_(style|kind|type|mode)$/, '')
    .replace(/_(mm|deg)$/, '')
    .replace(/_/g, ' ');
}

function axisNote(axis: string, up: boolean): string {
  if (axis === 'wall') {
    return up ? 'thicker walls' : 'thinner walls - watch the nozzle';
  }
  return `${up ? 'more' : 'less'} ${axis}, by a quarter`;
}

/**
 * The sentence for changing one assumed number to something specific.
 *
 * WHY IT IS PHRASED THIS WAY. The parser reads a number with a unit against
 * an axis word - "make it 200mm tall" - rather than a field name, because rule
 * 32 says the parameter is the implementation and English is the interface.
 * So an assumption named `height_mm` becomes "make it 200mm tall" and not
 * "set height_mm to 200".
 *
 * Returns null when the assumption's name is not one of the axes the parser
 * has a word for. That is not a gap to paper over: the value is still shown
 * and still explained, and the box still takes any sentence - what it does not
 * get is a one-tap phrasing that might not parse.
 */
export function sayForAssumption(name: string, value: number | string, units: string): string | null {
  if (typeof value !== 'number') return null;
  if (units && units !== 'mm') return null;

  for (const { axis } of AXES) {
    if (name === `${axis}_mm` || name === axis || name.startsWith(`${axis}_`)) {
      const word = ADJECTIVE[axis];
      if (!word) return null;
      return `make it ${trim(value)}mm ${word}`;
    }
  }
  return null;
}

/**
 * The adjective people use for each axis.
 *
 * Straight out of AXIS_WORDS in language.py, and the comment there is the
 * reason: nobody says "make it 200mm height", they say "tall". Without these
 * the explicit-dimension path misses the most ordinary sentence there is.
 */
const ADJECTIVE: Record<string, string> = {
  height: 'tall',
  width: 'wide',
  depth: 'deep',
  wall: 'thick',
};

function trim(value: number): string {
  return String(Number(value.toFixed(2)));
}

// ---------------------------------------------------------------------------
// the numbers, as things to drag
// ---------------------------------------------------------------------------

/**
 * One of a part's own numbers, ready to put a slider on.
 *
 * `low` and `high` are the TEMPLATE'S OWN bounds, straight off the Pydantic
 * schema - `wall_mm` is `gt=0.4, le=30.0` because that is what the template
 * accepts. A client inventing its own range would be guessing at a dimension,
 * which rule 9 forbids, and would offer values the builder then refuses.
 */
export interface Dimension {
  name: string;
  /** What a person calls it: `roof_pitch_deg` is "roof pitch". */
  label: string;
  value: number;
  low: number;
  high: number;
  units: string;
  /** Whole numbers only - a count of holes has no halves. */
  whole: boolean;
  description: string;
  /** True when nobody chose this: it is one of the engine's assumptions. */
  assumed: boolean;
}

/**
 * Every number on this part that can be dragged, with the value it holds now.
 *
 * WHAT IS LEFT OUT, AND WHY. A parameter with no bounds on both sides gets no
 * slider: the ends would have to be invented here, which rule 29 forbids in
 * the engine and which would be no better in the client. It still appears as a
 * value, it simply has nothing to drag.
 *
 * ASSUMED ONES COME FIRST. For a two-word request every number was chosen by
 * the engine, and those are precisely the ones a person is here to move - so
 * they sort above the ones that were asked for or left at the template's
 * default.
 */
export function dimensionsOf(
  template: TemplateInfo | null,
  current: Record<string, unknown>,
  assumed: string[] = [],
): Dimension[] {
  if (!template) return [];
  const out: Dimension[] = [];

  for (const parameter of template.params) {
    if (parameter.type !== 'float' && parameter.type !== 'int') continue;

    const low = firstNumber(parameter.bounds?.ge, parameter.bounds?.gt);
    const high = firstNumber(parameter.bounds?.le, parameter.bounds?.lt);
    if (low === null || high === null || !(high > low)) continue;

    // The spec's value, then the schema default. A parameter the spec leaves
    // out and the schema defaults to null has no value at all - the template
    // works it out at build time, which is what makes it an assumption - so
    // the assumption's own figure is the only honest starting point and it is
    // not in this payload. Those are shown but not dragged.
    const held = current[parameter.name] ?? parameter.default;
    if (typeof held !== 'number' || !Number.isFinite(held)) continue;

    out.push({
      name: parameter.name,
      label: readable(parameter.name).replace(/ (mm|deg)$/, ''),
      value: held,
      low,
      high,
      units: parameter.units,
      whole: parameter.type === 'int',
      description: parameter.description,
      assumed: assumed.includes(parameter.name),
    });
  }

  // Assumed first, then the order the schema declares - which is the order the
  // template author put them in, and reads better than alphabetical.
  return out.sort((a, b) => Number(b.assumed) - Number(a.assumed));
}

/**
 * The same thing for a part with no template: the server's own list.
 *
 * WHY THIS IS A MAPPER AND NOT ANOTHER DERIVATION. A template part's
 * dimensions are worked out here, from a schema this client fetches by name.
 * An ops spec has no template and no parameter names - its numbers sit at
 * positions in a list and their bounds are on the op models in Python - so
 * the server reads the bounds it owns and sends the list, and all that is
 * left here is turning a payload into what a slider takes.
 *
 * NOTHING IS MARKED ASSUMED. For a template part that flag means "the engine
 * chose this rather than being told", and it comes from the part's recorded
 * assumptions, which are named after template parameters. An ops number has
 * no such name to match, so claiming either way would be inventing
 * provenance. They are all simply the part's numbers.
 */
export function dimensionsFromOps(served: ServedDimension[] | undefined): Dimension[] {
  if (!served?.length) return [];
  return served.map((one) => ({
    name: one.name,
    label: one.label,
    value: one.value,
    low: one.low,
    high: one.high,
    units: one.units ?? '',
    whole: one.whole,
    description: one.description ?? '',
    assumed: false,
  }));
}

function firstNumber(...values: (number | undefined)[]): number | null {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

// ---------------------------------------------------------------------------
// the other half: somebody else's mesh
// ---------------------------------------------------------------------------

/**
 * Sentences the MESH parser reads, for a model that arrived as a file.
 *
 * A DIFFERENT PARSER, AND DELIBERATELY SO. whittle/edit/intent.py reads
 * sentences about a mesh - hollow it, cut it to fit the bed - and works on
 * somebody else's geometry, where there is no parametric model behind it and
 * nothing a triangle soup cannot do. whittle/spec/language.py reads sentences
 * about a SPEC. Which one applies is decided by whether the thing open has a
 * spec behind it, so the suggestions differ too.
 *
 * EVERY PHRASE IS ONE intent.py MATCHES, checked against its own regexes:
 * `\bhollow(ed|ing)?\b`, `\b(cut|split|slice|chop)\b`,
 * `\bflat(ten)?\b.*\b(base|bottom)\b`, and so on. A phrase invented here would
 * land in `unmapped` and be reported back as "nothing matched", which is the
 * parser behaving correctly and the app looking broken.
 */
const MESH_TWEAKS: { kind: string; say: string; note: string }[] = [
  {
    kind: 'hollow',
    say: 'hollow it to 2mm',
    note: 'takes the middle out, leaving a wall - far less plastic and time',
  },
  {
    kind: 'cut_plane',
    say: 'cut it to fit my bed',
    note: 'splits it where the bed runs out, so it prints in parts',
  },
  {
    kind: 'flatten_base',
    say: 'flatten the base so it stands',
    note: 'cuts a flat face - a model that rocks on the bed does not stick',
  },
  {
    kind: 'scale_to_height',
    say: 'make it 80mm tall',
    note: 'scales the whole thing to that measurement',
  },
  { kind: 'scale_uniform', say: 'make it smaller', note: 'every dimension at once' },
  {
    kind: 'thicken_thin_walls',
    say: 'make the walls thicker',
    note: 'inflates anything thinner than the nozzle can print',
  },
  {
    kind: 'remove_floaters',
    say: 'clean it up',
    note: 'deletes disconnected specks and stray shells',
  },
  { kind: 'rotate', say: 'rotate it 90 degrees', note: 'turns it about its own centre' },
  { kind: 'mirror', say: 'mirror it', note: 'flips it, and fixes the winding that reverses' },
];

/**
 * The mesh sentences this engine can actually carry out.
 *
 * FILTERED BY THE SERVER'S OWN REGISTRY. /api/operations is the registry
 * itself, and `not_built_yet` is a real list - auto_orient, add_base,
 * emboss_text and nine others are named and not implemented. Offering one
 * would be offering a change that cannot happen, and the catalogue exists so a
 * client cannot do that.
 */
export function meshTweaks(catalogue: Catalogue | null): Tweak[] {
  if (!catalogue) return [];
  const built = new Set(catalogue.operations.map((op) => op.kind));
  return MESH_TWEAKS.filter((t) => built.has(t.kind)).map(({ say, note }) => ({ say, note }));
}

/**
 * An operation's machine name as a person would say it.
 *
 * `thicken_thin_walls` is "thicken thin walls". The registry's names are
 * identifiers and the screen was printing them raw - rule 32's split again,
 * on the one screen where the operations ARE the interface.
 */
export function operationLabel(kind: string): string {
  return kind.replace(/_/g, ' ');
}
