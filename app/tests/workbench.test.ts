/**
 * One object, one loop - the part of it that can be checked without a screen.
 *
 * WHAT THESE TESTS ARE FOR. There is no way to look at a phone from here, so
 * anything that only exists as layout is unverifiable and anything that can be
 * pulled out of the layout should be. The two things worth pulling out are the
 * ones that were actually wrong:
 *
 *   1. a sentence went to the wrong half of the engine, so the box was not
 *      drawn at all on an import
 *   2. the same verdict was described in two different vocabularies depending
 *      on which screen you were looking at
 *
 * Both are logic. Both are here.
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  PANELS,
  openAt,
  sayHint,
  sayTo,
  sizeLine,
  standingOfPart,
  standingOfProject,
  type Origin,
} from '../src/workbench.ts';

// ---------------------------------------------------------------------------
// the same words for the same state, whatever the object came from
// ---------------------------------------------------------------------------

test('a part that prints and a mesh that prints say the same word', () => {
  const part = standingOfPart({
    size_mm: [120, 90, 70],
    volume_cm3: 34.2,
    checks: {
      verdict: 'pass', ok: true, problems: [], warnings: [], nozzle_mm: 0.4,
      material: 'pla', print_axis: 'z', lines: [], source: 'stored',
      checked_at: 0, drift: [],
    },
  });
  const mesh = standingOfProject({
    id: 'p1', name: 'thing', format: 'stl',
    units: { units: 'mm', assumed: false, reason: '', alternatives: [] },
    repair: { changed: false, steps: [], unresolved: [] },
    size_mm: [120, 90, 70], triangles: 4000, bodies: 1, edits: [],
    report: { printable: true, findings: [], measurements: {} },
  });

  assert.equal(part.headline, 'prints');
  assert.equal(mesh.headline, part.headline);
  assert.equal(part.tone, 'pass');
  assert.equal(mesh.tone, 'pass');
});

test('a part that will not print and a mesh that will not print say the same word', () => {
  const part = standingOfPart({
    checks: {
      verdict: 'fail', ok: false,
      problems: ['545 mm2 of underside overhangs past 45 degrees'],
      warnings: [], nozzle_mm: 0.4, material: 'pla', print_axis: 'z',
      lines: [], source: 'stored', checked_at: 0, drift: [],
    },
  });
  const mesh = standingOfProject({
    id: 'p1', name: 'thing', format: 'stl',
    units: { units: 'mm', assumed: false, reason: '', alternatives: [] },
    repair: { changed: false, steps: [], unresolved: [] },
    size_mm: [10, 10, 10], triangles: 12, bodies: 1, edits: [],
    report: {
      printable: false, measurements: {},
      findings: [{ severity: 'fail', rule: 'overhang', detail: 'it overhangs', fix: '', value: null }],
    },
  });

  assert.equal(part.headline, 'will not print as it is');
  assert.equal(mesh.headline, part.headline);
  assert.equal(part.tone, 'fail');
  assert.equal(mesh.tone, 'fail');
});

test("the reason a part will not print is the engine's own words, not an apology", () => {
  const standing = standingOfPart({
    size_mm: [10, 10, 10],
    checks: {
      verdict: 'fail', ok: false,
      problems: ['545 mm2 of underside overhangs past 45 degrees'],
      warnings: [], nozzle_mm: 0.4, material: 'pla', print_axis: 'z',
      lines: [], source: 'stored', checked_at: 0, drift: [],
    },
  });
  assert.match(standing.detail, /545 mm2/);
});

test('a verdict taken against a printer profile that has moved is not a tick', () => {
  const standing = standingOfPart({
    checks: {
      verdict: 'pass', ok: true, problems: [], warnings: [], nozzle_mm: 0.4,
      material: 'pla', print_axis: 'z', lines: [], source: 'stored',
      checked_at: 0, drift: ['the nozzle is 0.6 mm now, it was 0.4'],
    },
  });
  assert.equal(standing.tone, 'warn');
  assert.equal(standing.stale, true);
  assert.match(standing.detail, /0.6 mm/);
});

test('a mesh mid-drag says it is catching up rather than showing the old verdict', () => {
  const standing = standingOfProject({
    id: 'p1', name: 'thing', format: 'stl',
    units: { units: 'mm', assumed: false, reason: '', alternatives: [] },
    repair: { changed: false, steps: [], unresolved: [] },
    size_mm: [10, 10, 10], triangles: 12, bodies: 1, edits: [],
    report: { printable: true, findings: [], measurements: {}, stale: true },
  });
  assert.equal(standing.stale, true);
  assert.notEqual(standing.headline, 'prints');
});

test('an object nobody has checked says so rather than passing', () => {
  assert.equal(standingOfPart(null).tone, 'unknown');
  assert.equal(standingOfProject(null).tone, 'unknown');
});

test('the size is rounded to whole millimetres and never half a number', () => {
  assert.equal(sizeLine([120.4, 89.6, 70]), '120 × 90 × 70 mm');
  assert.equal(sizeLine([120, 90]), '');
  assert.equal(sizeLine(null), '');
});

// ---------------------------------------------------------------------------
// the sentence goes to the right half of the engine
// ---------------------------------------------------------------------------

test('a sentence about a built part goes to refine, and starts a build', async () => {
  const calls: string[] = [];
  const api = {
    refine: async (name: string, sentence: string) => {
      calls.push(`refine:${name}:${sentence}`);
      return { job: 'j7' };
    },
    say: async () => {
      throw new Error('a part must not be sent to the project route');
    },
  } as never;

  const reply = await sayTo(api, { kind: 'part', name: 'birdhouse_2' }, 'make it taller');
  assert.deepEqual(calls, ['refine:birdhouse_2:make it taller']);
  assert.deepEqual(reply, { at: 'part', jobId: 'j7' });
});

test('a sentence about an imported mesh goes to say, and comes back with the mesh', async () => {
  const said = { echo: 'hollowed it', unmapped: [], questions: [], applied: [], project: {} };
  const calls: string[] = [];
  const api = {
    refine: async () => {
      // THE BUG THIS TEST EXISTS FOR. /api/refine answers "no part called x,
      // or it has no spec.yaml to change" for a mesh. The old screen's answer
      // was to draw no box at all on an import, so there was nowhere to say
      // anything to a model somebody had just brought in.
      throw new Error('a mesh must not be sent to the part route');
    },
    say: async (id: string, sentence: string) => {
      calls.push(`say:${id}:${sentence}`);
      return said;
    },
  } as never;

  const reply = await sayTo(api, { kind: 'project', id: 'p42' }, 'hollow it to 2mm');
  assert.deepEqual(calls, ['say:p42:hollow it to 2mm']);
  assert.equal(reply.at, 'project');
});

test('both origins get a box, and the examples suit what they are', () => {
  const part: Origin = { kind: 'part', name: 'birdhouse' };
  const mesh: Origin = { kind: 'project', id: 'p1' };

  assert.ok(sayHint(part).length > 0);
  assert.ok(sayHint(mesh).length > 0);
  assert.notEqual(sayHint(part), sayHint(mesh));
  // A hint the part's own schema produced beats the generic one.
  assert.equal(sayHint(part, 'make the roof triangular'), 'make the roof triangular');
});

// ---------------------------------------------------------------------------
// the drawer
// ---------------------------------------------------------------------------

test('there is one set of panel names, not one per screen', () => {
  assert.deepEqual([...PANELS], ['shape', 'prints', 'about', 'save']);
});

test('a broken object opens on the reason, a working one on the numbers', () => {
  assert.equal(openAt({ tone: 'fail', headline: '', detail: '', stale: false }), 'prints');
  assert.equal(openAt({ tone: 'pass', headline: '', detail: '', stale: false }), 'shape');
  assert.equal(openAt({ tone: 'warn', headline: '', detail: '', stale: false }), 'shape');
});
