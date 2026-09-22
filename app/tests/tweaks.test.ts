/**
 * The change words, against the templates the engine actually has.
 *
 *     npm test
 *
 * WHY A FIXTURE OF REAL SCHEMAS. These suggestions are the whole of what a
 * person is offered after typing two words, and the one way they can go wrong
 * is by offering a change the engine will decline - "make it taller" on a
 * bracket, which has no height field at all. A test against a made-up template
 * would prove the filter runs; only the real schemas prove it filters the
 * right things.
 *
 * fixtures/templates.json is `api.template_info` for every registered
 * template, written by the same call the app makes. Regenerate it with:
 *
 *     python3 -c "from whittle import api, json; ..."   (see the repo notes)
 *
 * and a template that changes shape shows up here as a failing expectation
 * rather than as a dead chip on a phone.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import type { TemplateInfo } from '../src/api.ts';
import { dimensionsOf, sayForAssumption, tweaksFor } from '../src/tweaks.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const TEMPLATES: Record<string, TemplateInfo> = JSON.parse(
  readFileSync(join(HERE, 'fixtures', 'templates.json'), 'utf8'),
);

const said = (t: TemplateInfo, current: Record<string, unknown> = {}) =>
  tweaksFor(t, current).map((tweak) => tweak.say);

// ---------------------------------------------------------------------------
// only what the part actually has
// ---------------------------------------------------------------------------

test('a bracket is not offered "taller", because a bracket has no height', () => {
  // THE PARSER WOULD REFUSE IT. `_field_ending` in language.py matches an axis
  // against the template's own field names and returns nothing rather than
  // moving whatever field sorts first - so offering the word here would
  // produce a chip that does nothing, which teaches people not to trust the
  // chips that work.
  const bracket = TEMPLATES.bracket;
  assert.ok(bracket, 'the fixture has no bracket');
  assert.equal(
    bracket.params.some((p) => p.name === 'height_mm' || p.name === 'height'),
    false,
    'the bracket gained a height field - this test is now wrong, not the code',
  );
  assert.equal(said(bracket).includes('make it taller'), false);
  assert.equal(said(bracket).includes('make it shorter'), false);
});

test('a bracket IS offered "wider" and "thicker", which it has', () => {
  const words = said(TEMPLATES.bracket);
  assert.ok(words.includes('make it wider'), 'bracket has width_mm');
  assert.ok(words.includes('make it narrower'));
  // thickness_mm is not wall_mm, and "thicker" maps to the wall axis - so this
  // asserts what the PARSER would do rather than what reads nicely.
  assert.equal(
    TEMPLATES.bracket.params.some((p) => p.name.startsWith('wall_')),
    true,
    'wall_length_mm is what makes the wall axis match on a bracket',
  );
});

test('an enclosure is offered every principal axis', () => {
  const words = said(TEMPLATES.enclosure);
  for (const word of ['taller', 'shorter', 'wider', 'narrower', 'deeper', 'shallower']) {
    assert.ok(words.includes(`make it ${word}`), `enclosure should offer ${word}`);
  }
});

test('"bigger" and "smaller" lead, because that is the first thing anybody says', () => {
  const words = said(TEMPLATES.enclosure);
  assert.equal(words[0], 'make it bigger');
  assert.equal(words[1], 'make it smaller');
});

test('no template means no suggestions, not invented ones', () => {
  // An imported mesh has no spec behind it. The box still takes any sentence.
  assert.deepEqual(tweaksFor(null), []);
});

// ---------------------------------------------------------------------------
// the choices, which are the interesting ones
// ---------------------------------------------------------------------------

test('the roof choices reach the screen at all', () => {
  // THE PAYLOAD USED TO CARRY NONE. A Literal's arguments are values, so
  // `roof_style: Literal["flat","mono","gable"]` reported its type as "flat"
  // and listed no choices anywhere - the one field a person is most likely to
  // change described itself as one of its own answers.
  const roof = TEMPLATES.enclosure.params.find((p) => p.name === 'roof_style');
  assert.ok(roof, 'the enclosure has no roof_style');
  assert.deepEqual(roof.choices, ['flat', 'mono', 'gable']);
  assert.equal(roof.type, 'choice');
});

test('a gable roof is not offered a gable roof', () => {
  // THE SCHEMA DEFAULT IS NOT THE CURRENT VALUE. roof_style defaults to "mono"
  // and the birdhouse in this library is a gable, so filtering on the default
  // alone suggested "make the roof gable" on a part that already had one - a
  // rebuild that produces an identical part, which reads as the app ignoring
  // you.
  const words = said(TEMPLATES.enclosure, { roof_style: 'gable' });
  assert.equal(words.includes('make the roof gable'), false);
  assert.ok(words.includes('make the roof flat'));
  assert.ok(words.includes('make the roof mono'));
});

test('with no spec value it falls back to the schema default', () => {
  const words = said(TEMPLATES.enclosure);
  assert.equal(words.includes('make the roof mono'), false, 'mono is the default');
  assert.ok(words.includes('make the roof gable'));
});

test('the schema suffix people never say out loud is dropped', () => {
  // `roof_style` is "the roof". Rule 32's split: the parameter is the
  // implementation, the English is the interface.
  const words = said(TEMPLATES.enclosure, { roof_style: 'flat' });
  assert.ok(words.includes('make the roof gable'));
  assert.equal(
    words.some((w) => w.includes('roof style')),
    false,
    'nobody says "make the roof style gable"',
  );
});

// ---------------------------------------------------------------------------
// the things that are there or not
// ---------------------------------------------------------------------------

test('a bracket that has a gusset is offered "no gusset", not "add a gusset"', () => {
  // The parser skips a change to the value already in force, so offering both
  // directions puts a chip on screen that does nothing when tapped.
  const words = said(TEMPLATES.bracket, { gusset: true });
  assert.ok(words.includes('no gusset'));
  assert.equal(words.includes('add a gusset'), false);
});

test('and one without a gusset is offered one', () => {
  const words = said(TEMPLATES.bracket, { gusset: false });
  assert.ok(words.includes('add a gusset'));
  assert.equal(words.includes('no gusset'), false);
});

test('with no spec value the schema default decides the direction', () => {
  // gusset defaults to true, so the useful offer is taking it off.
  assert.ok(said(TEMPLATES.bracket).includes('no gusset'));
});

test('the enclosure can be asked for no roof', () => {
  // "no roof" is one of the four examples in language.py's own docstring.
  assert.ok(said(TEMPLATES.enclosure, { roof: true }).includes('no roof'));
});

test('every suggested sentence is one a person would actually say', () => {
  for (const [name, template] of Object.entries(TEMPLATES)) {
    for (const tweak of tweaksFor(template)) {
      assert.match(
        tweak.say,
        /^(make (it|the) [a-z0-9 ]+|no [a-z0-9 ]+|add a [a-z0-9 ]+)$/,
        `${name} suggested ${tweak.say!}, which is not a sentence`,
      );
      assert.ok(tweak.note, `${name}: ${tweak.say} has no explanation`);
      // A field name leaking into the suggestion is the rule-32 failure this
      // whole file is about.
      assert.equal(tweak.say.includes('_'), false, `${name}: ${tweak.say} leaks a field name`);
    }
  }
});

// ---------------------------------------------------------------------------
// an assumed number, turned into a sentence
// ---------------------------------------------------------------------------

test('an assumed height becomes the adjective, not the field name', () => {
  // "make it 200mm height" is not English and the parser does not read it.
  assert.equal(sayForAssumption('height_mm', 200, 'mm'), 'make it 200mm tall');
  assert.equal(sayForAssumption('width_mm', 60.5, 'mm'), 'make it 60.5mm wide');
  assert.equal(sayForAssumption('wall_mm', 2.4, 'mm'), 'make it 2.4mm thick');
});

test('an assumption the parser has no word for offers no tap', () => {
  // corner_r_mm and edge_margin_mm are the two the bracket actually assumes,
  // and neither is an axis the parser has an adjective for. They still show
  // their value and their reason - what they do not get is a one-tap phrasing
  // that would fail.
  assert.equal(sayForAssumption('corner_r_mm', 9.0, 'mm'), null);
  assert.equal(sayForAssumption('edge_margin_mm', 7.7, 'mm'), null);
});

test('a non-length assumption is never phrased as a length', () => {
  // "30 degrees" becoming 30 mm somewhere is the exact failure language.py
  // keeps its ANGLES set to prevent.
  assert.equal(sayForAssumption('roof_pitch_deg', 18, 'deg'), null);
  assert.equal(sayForAssumption('height_mm', 'auto', 'mm'), null);
});

test('a value is not given digits it did not have', () => {
  assert.equal(sayForAssumption('height_mm', 140, 'mm'), 'make it 140mm tall');
  assert.equal(sayForAssumption('height_mm', 140.004, 'mm'), 'make it 140mm tall');
});

// ---------------------------------------------------------------------------
// the numbers, as things to drag
// ---------------------------------------------------------------------------

test('a slider gets the template\u2019s own limits, never invented ones', () => {
  const dims = dimensionsOf(TEMPLATES.enclosure, { width_mm: 120 });
  const width = dims.find((d) => d.name === 'width_mm');
  assert.ok(width, 'the enclosure has no draggable width');
  // wall_mm is gt=0.4, le=30.0 because that is what the template accepts. A
  // client inventing a range would offer values the builder then refuses.
  const wall = dims.find((d) => d.name === 'wall_mm');
  assert.equal(wall?.low, 0.4);
  assert.equal(wall?.high, 30);
});

test('the current value wins over the schema default', () => {
  const dims = dimensionsOf(TEMPLATES.enclosure, { width_mm: 150 });
  assert.equal(dims.find((d) => d.name === 'width_mm')?.value, 150);
  // And a field the spec does not mention falls back to the default.
  assert.equal(dims.find((d) => d.name === 'height_mm')?.value, 160);
});

test('a parameter with no value at all gets no slider', () => {
  // floor_mm defaults to null: the template works it out at build time, which
  // is what makes it an assumption. Starting a slider at zero would be a
  // number nobody chose.
  const floor = TEMPLATES.enclosure.params.find((p) => p.name === 'floor_mm');
  assert.equal(floor?.default, null, 'floor_mm stopped defaulting to null');
  assert.equal(
    dimensionsOf(TEMPLATES.enclosure, {}).some((d) => d.name === 'floor_mm'),
    false,
  );
});

test('the ones the engine chose sort to the top', () => {
  // For a two-word request most numbers are assumptions, and those are the
  // ones a person came here to move.
  const dims = dimensionsOf(TEMPLATES.enclosure, { width_mm: 120 }, ['roof_pitch_deg']);
  assert.equal(dims[0].name, 'roof_pitch_deg');
  assert.equal(dims[0].assumed, true);
  assert.equal(dims[1].assumed, false);
});

test('a count is whole and a length is not', () => {
  const dims = dimensionsOf(TEMPLATES.enclosure, {});
  assert.equal(dims.find((d) => d.name === 'drain_holes')?.whole, true);
  assert.equal(dims.find((d) => d.name === 'width_mm')?.whole, false);
});

test('the label is what a person calls it, not what the schema calls it', () => {
  const dims = dimensionsOf(TEMPLATES.enclosure, {});
  assert.equal(dims.find((d) => d.name === 'roof_pitch_deg')?.label, 'roof pitch');
  assert.equal(dims.find((d) => d.name === 'width_mm')?.label, 'width');
  for (const dimension of dims) {
    assert.equal(dimension.label.includes('_'), false, `${dimension.name} leaks its field name`);
  }
});

test('no template, no sliders - an imported mesh has no spec behind it', () => {
  assert.deepEqual(dimensionsOf(null, { width_mm: 120 }), []);
});

test('every template yields sliders whose ends are real and ordered', () => {
  for (const [name, template] of Object.entries(TEMPLATES)) {
    for (const dimension of dimensionsOf(template, {})) {
      assert.ok(
        dimension.high > dimension.low,
        `${name}.${dimension.name} has ends ${dimension.low}..${dimension.high}`,
      );
      assert.ok(
        dimension.value >= dimension.low && dimension.value <= dimension.high,
        `${name}.${dimension.name} starts at ${dimension.value}, outside its own bounds`,
      );
    }
  }
});
