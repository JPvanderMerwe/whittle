/**
 * The two pure functions on the client that carry a rule.
 *
 *     npm test
 *
 * Neither of these is about layout. `measuredAgainst` writes the line on the
 * landing screen that says what a request will be checked against, and rule 29
 * says a value with no measured source must not be replaced by a plausible one
 * - so the interesting cases are all the ones where a field is missing, UNSET
 * or the wrong type. `cleanBase` is the only place in the app where a person
 * types something the app then talks to.
 *
 * Both are tested here rather than through a screen because a screen test
 * would prove React renders, which is not in doubt.
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { Health } from '../src/api.ts';
import { measuredAgainst, nowrap } from '../src/machine.ts';
import { cleanBase, isLoopback } from '../src/address.ts';

/** A health payload with everything set, as config/default.toml pins it. */
function health(over: Partial<Health> = {}): Health {
  return {
    model: { ok: true },
    capability: { tier: 'gpu', headline: '' },
    printer: { name: 'Creality i7', multi_colour: true },
    bed: { width_mm: 260.0, depth_mm: 260.0, height_mm: 255.0 },
    print: { nozzle_mm: 0.4, layer_mm: 0.2 },
    materials: ['asa', 'petg', 'petg_cf', 'pla', 'tpu'],
    material_default: 'petg',
    templates: [],
    ...over,
  };
}

// ---------------------------------------------------------------------------
// what a request will be measured against
// ---------------------------------------------------------------------------

test('the whole line, in the order a person reads it', () => {
  assert.deepEqual(measuredAgainst(health(), 'pla'), [
    'Creality i7',
    '260 × 260 × 255 mm bed',
    '0.4 mm nozzle',
    'pla',
  ]);
});

test('no machine means no line at all, not a line of blanks', () => {
  assert.deepEqual(measuredAgainst(null, 'pla'), []);
});

test('the material is the SERVER’s default, never the head of a sorted list', () => {
  // THIS IS THE BUG THIS TEST EXISTS FOR. `materials` is sorted, so its head is
  // whatever happens to sort first. The day the shop's full stock went into the
  // config that became "asa" - and the line would have said the part was being
  // built in ASA while the server was still building it in PETG.
  assert.equal(measuredAgainst(health(), null).at(-1), 'petg');
  assert.equal(measuredAgainst(health(), 'tpu').at(-1), 'tpu', 'a choice wins');
});

test('an engine that does not publish its default names no material at all', () => {
  // A missing word beats a wrong one: this whole line exists to be trusted.
  const older = health();
  delete (older as { material_default?: string }).material_default;
  assert.equal(measuredAgainst(older, null).at(-1), '0.4 mm nozzle');
});

test('an UNSET printer name is dropped rather than printed', () => {
  // RULE 29 REACHES THE SCREEN. config.UNSET is the string "UNSET" and it is
  // served as-is; drawing it would put the word in the middle of the line.
  const line = measuredAgainst(health({ printer: { name: 'UNSET' } }), 'pla');
  assert.equal(line.includes('UNSET'), false);
  assert.equal(line[0], '260 × 260 × 255 mm bed');
});

test('a bed missing one of its three dimensions is not drawn as a partial bed', () => {
  // An unconfigured bed is what rule 29 is about: the does-it-fit check cannot
  // run, and "260 × 260 × undefined" would look like it could.
  const line = measuredAgainst(health({ bed: { width_mm: 260, depth_mm: 260 } }), 'pla');
  assert.deepEqual(line, ['Creality i7', '0.4 mm nozzle', 'pla']);
});

test('an engine with no print section - one version behind - simply omits the nozzle', () => {
  const older = health();
  delete (older as { print?: unknown }).print;
  assert.deepEqual(measuredAgainst(older, 'pla'), [
    'Creality i7',
    '260 × 260 × 255 mm bed',
    'pla',
  ]);
});

test('an UNSET nozzle is a string, and a string is not a measurement', () => {
  const line = measuredAgainst(health({ print: { nozzle_mm: 'UNSET' } }), 'pla');
  assert.equal(
    line.some((bit) => bit.includes('nozzle')),
    false,
  );
});

test('trailing zeros are trimmed without inventing digits', () => {
  const line = measuredAgainst(
    health({ bed: { width_mm: 220.0, depth_mm: 220.0, height_mm: 250.5 } }),
    'pla',
  );
  assert.equal(line[1], '220 × 220 × 250.5 mm bed');
});

// ---------------------------------------------------------------------------
// the address somebody types
// ---------------------------------------------------------------------------

test('a bare host gets the scheme and the port whittle listens on', () => {
  // A HOST WITH NO PORT REACHES PORT 80 AND TIMES OUT, which a person reads as
  // "the machine is off" rather than as a typo.
  assert.equal(cleanBase('192.168.1.40'), 'http://192.168.1.40:8765');
});

test('a trailing slash is removed, because every path would otherwise double it', () => {
  assert.equal(cleanBase('http://192.168.1.40:8765/'), 'http://192.168.1.40:8765');
  assert.equal(cleanBase('http://192.168.1.40:8765///'), 'http://192.168.1.40:8765');
});

test('whitespace from a paste is invisible on screen and is stripped', () => {
  assert.equal(cleanBase('  192.168.1.40:8765  '), 'http://192.168.1.40:8765');
});

test('an explicit port is kept', () => {
  assert.equal(cleanBase('http://box.local:9000'), 'http://box.local:9000');
});

test('https is not rewritten to http', () => {
  assert.equal(cleanBase('https://box.local:8765'), 'https://box.local:8765');
});

test('nothing typed, and nothing that can be a host, is refused rather than guessed', () => {
  assert.equal(cleanBase(''), null);
  assert.equal(cleanBase('   '), null);
  assert.equal(cleanBase('http://'), null);
});

test('loopback is recognised however it is spelled', () => {
  assert.equal(isLoopback('http://127.0.0.1:8765'), true);
  assert.equal(isLoopback('http://localhost:8765'), true);
  assert.equal(isLoopback('http://192.168.1.40:8765'), false);
  // The screen says something different for each, so a wrong answer here tells
  // somebody their geometry is off the network when it is on it.
  assert.equal(isLoopback('not an address'), false);
});

test('a phrase is held together when the line it sits on wraps', () => {
  // "0.4 mm" on one row and "nozzle" on the next reads for a moment as two
  // separate facts. The data stays plain so the tests above can assert it; the
  // non-breaking spaces go in where the line is drawn.
  assert.equal(nowrap('0.4 mm nozzle'), '0.4 mm nozzle');
  assert.equal(nowrap('petg'), 'petg');
  // And the joiner between phrases is NOT touched, or the whole line becomes
  // one unbreakable string and overflows instead of wrapping.
  assert.equal(measuredAgainst(health(), 'pla').map(nowrap).join('  ·  ').includes('  ·  '), true);
});
