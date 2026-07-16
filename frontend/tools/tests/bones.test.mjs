// Validates the committed bones JSON and that they render via the vendored core.
// Run: node --test frontend/tools/tests/bones.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { renderBones } from '../../js/vendor/boneyard/runtime.js';
import { resolveResponsive } from '../../js/vendor/boneyard/shared.js';
import { BREAKPOINTS, FIXTURES } from '../bone-fixtures.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const BONES_DIR = path.join(here, '..', '..', 'js', 'bones');

const componentNames = FIXTURES.map(f => f.name);

test('every fixture has a committed .bones.json', () => {
  for (const name of componentNames) {
    const file = path.join(BONES_DIR, `${name}.bones.json`);
    assert.ok(fs.existsSync(file), `missing ${name}.bones.json`);
  }
});

for (const name of componentNames) {
  test(`${name}: valid responsive bones at all breakpoints`, () => {
    const raw = fs.readFileSync(path.join(BONES_DIR, `${name}.bones.json`), 'utf8');
    const data = JSON.parse(raw); // throws on malformed JSON
    assert.equal(data.name, name);
    assert.ok(data.breakpoints, 'has breakpoints');
    for (const bp of BREAKPOINTS) {
      const skel = data.breakpoints[String(bp)];
      assert.ok(skel, `${name} missing breakpoint ${bp}`);
      assert.ok(skel.width > 0, `${name}@${bp} width>0`);
      assert.ok(skel.height > 0, `${name}@${bp} height>0`);
      assert.ok(Array.isArray(skel.bones) && skel.bones.length > 0, `${name}@${bp} has bones`);
      for (const b of skel.bones) {
        assert.ok(b.w >= 0 && b.w <= 100.001, `${name}@${bp} bone x-width is a %`);
        assert.ok(b.h >= 0, `${name}@${bp} bone height >= 0`);
      }
    }
  });

  test(`${name}: renders to HTML at desktop width`, () => {
    const data = JSON.parse(fs.readFileSync(path.join(BONES_DIR, `${name}.bones.json`), 'utf8'));
    const skel = resolveResponsive(data, 1280);
    assert.ok(skel, 'resolveResponsive returns a result');
    const html = renderBones(skel, '#e6ddd2', false);
    assert.ok(html.includes('boneyard-bone'), 'has bones');
    assert.ok(html.includes(`height:${skel.height}px`), 'container height set');
  });
}
