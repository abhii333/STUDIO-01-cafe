// Tests for the skeleton runtime pure helpers + generated bundle integrity.
// Run: node --test frontend/tools/tests/runtime.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { clampCount } from '../../js/skeleton-runtime.mjs';
import { ALL_BONES } from '../../js/bones/index.mjs';
import { FIXTURES } from '../bone-fixtures.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const BONES_DIR = path.join(here, '..', '..', 'js', 'bones');

test('skeleton-runtime.mjs imports in Node without a window (guards work)', () => {
  // If the import above had thrown on window access, this test file would not run.
  assert.equal(typeof clampCount, 'function');
});

test('clampCount clamps to [1, max]', () => {
  assert.equal(clampCount(6), 6);
  assert.equal(clampCount(0), 1);
  assert.equal(clampCount(-3), 1);
  assert.equal(clampCount(999), 12);
  assert.equal(clampCount(undefined), 1);
  assert.equal(clampCount('4'), 4);
  assert.equal(clampCount(NaN), 1);
  assert.equal(clampCount(5, 3), 3);
});

test('bundled ALL_BONES matches the committed .bones.json (no drift)', () => {
  for (const fx of FIXTURES) {
    const json = JSON.parse(fs.readFileSync(path.join(BONES_DIR, `${fx.name}.bones.json`), 'utf8'));
    assert.deepEqual(ALL_BONES[fx.name], json, `${fx.name}: index.mjs out of sync — re-run build-bones-index.mjs`);
  }
  assert.equal(Object.keys(ALL_BONES).length, FIXTURES.length);
});
