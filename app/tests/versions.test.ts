/**
 * The chain of parts one request turns into.
 *
 *     npm test
 *
 * The cases here are the real library's, because the two that matter are both
 * in it: `birdhouse` and `birdhouse_2` ARE the same chain, and
 * `birdhouse_with_feeder_and_water_retainer` is NOT - and a grouping that gets
 * the second one wrong silently buries somebody's part inside another one's
 * history.
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { LibraryPart } from '../src/api.ts';
import {
  buildNumber,
  chainOf,
  chainSize,
  newestOfEachChain,
  stemOf,
} from '../src/versions.ts';

/** A library row with only the fields the chain logic reads. */
function part(dir: string, name: string): LibraryPart {
  return {
    name,
    dir,
    template: null,
    prompt: null,
    makes: [],
    size_mm: null,
    volume_cm3: null,
    bodies: null,
    material: null,
    level: null,
    when: '2026-09-14',
    built: true,
  };
}

// The rows this library actually has, newest first as the server serves them.
const LIBRARY = [
  part('birdhouse_3', 'birdhouse'),
  part('birdhouse_2', 'birdhouse'),
  part('birdhouse_with_feeder_and_water_retainer', 'birdhouse_with_feeder_and_water_retainer'),
  part('birdhouse', 'birdhouse'),
  part('keyring', 'loop_keyring'),
];

test('the allocator’s suffix is what a stem strips', () => {
  assert.equal(stemOf('birdhouse_2'), 'birdhouse');
  assert.equal(stemOf('birdhouse'), 'birdhouse');
  assert.equal(stemOf('birdhouse_999'), 'birdhouse');
  // NOT A NUMBER, NOT A SUFFIX. This is the case that matters: a part somebody
  // named for itself must not be swallowed by another one's chain.
  assert.equal(
    stemOf('birdhouse_with_feeder_and_water_retainer'),
    'birdhouse_with_feeder_and_water_retainer',
  );
});

test('the build number is the one the allocator put on the directory', () => {
  assert.equal(buildNumber('birdhouse'), 1);
  assert.equal(buildNumber('birdhouse_2'), 2);
  assert.equal(buildNumber('birdhouse_12'), 12);
  assert.equal(buildNumber('a_hinge'), 1, 'a trailing word is not a number');
});

test('a chain is every build of one part, oldest first', () => {
  const chain = chainOf(LIBRARY, part('birdhouse_2', 'birdhouse'));
  assert.deepEqual(
    chain.map((p) => p.dir),
    ['birdhouse', 'birdhouse_2', 'birdhouse_3'],
  );
});

test('a differently-named part is not swallowed by the chain it prefixes', () => {
  const feeder = LIBRARY[2];
  assert.deepEqual(chainOf(LIBRARY, feeder).map((p) => p.dir), [feeder.dir]);
  assert.equal(
    chainOf(LIBRARY, part('birdhouse', 'birdhouse')).some(
      (p) => p.dir === feeder.dir,
    ),
    false,
    'the feeder birdhouse ended up inside the plain birdhouse’s history',
  );
});

test('the spec name is the second signal, and it is load-bearing', () => {
  // Somebody names a part `foo_2` themselves. Its spec name is `foo_2`, not
  // `foo`, so it is its own chain - the directory stem alone would merge them.
  const rows = [part('foo', 'foo'), part('foo_2', 'foo_2')];
  assert.deepEqual(chainOf(rows, rows[0]).map((p) => p.dir), ['foo']);
  assert.deepEqual(chainOf(rows, rows[1]).map((p) => p.dir), ['foo_2']);
});

test('a part with no siblings is a chain of one, not an empty chain', () => {
  // So a caller can say "1 of 1" and hide the panel by length, with no special
  // case for the commonest part in any library.
  const chain = chainOf(LIBRARY, LIBRARY[4]);
  assert.equal(chain.length, 1);
  assert.equal(chain[0].dir, 'keyring');
});

test('the grid collapses a chain to its newest, keeping the served order', () => {
  const shown = newestOfEachChain(LIBRARY);
  assert.deepEqual(
    shown.map((p) => p.dir),
    ['birdhouse_3', 'birdhouse_with_feeder_and_water_retainer', 'keyring'],
  );
});

test('the count on a tile is the whole chain, not what is on screen', () => {
  assert.equal(chainSize(LIBRARY, part('birdhouse_3', 'birdhouse')), 3);
  assert.equal(chainSize(LIBRARY, LIBRARY[4]), 1);
});

test('collapsing an empty library is empty, not a crash', () => {
  assert.deepEqual(newestOfEachChain([]), []);
});
