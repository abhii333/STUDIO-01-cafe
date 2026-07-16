// Zero-dependency smoke test for the vendored Boneyard core.
// Run: node --test frontend/tools/tests/vendor.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';

import { renderBones } from '../../js/vendor/boneyard/runtime.js';
import { resolveResponsive, registerBones, getRegisteredBones } from '../../js/vendor/boneyard/shared.js';
import { normalizeBone } from '../../js/vendor/boneyard/types.js';

const fixture = {
  name: 'fixture',
  width: 300,
  height: 120,
  bones: [
    { x: 4, y: 10, w: 92, h: 20, r: 8 },   // leaf
    { x: 4, y: 40, w: 60, h: 14, r: 6 },   // leaf
    { x: 0, y: 0, w: 100, h: 120, r: 14, c: true }, // container -> must be skipped
  ],
};

test('renderBones returns HTML with .boneyard-bone and the container height', () => {
  const html = renderBones(fixture, '#e8e0d6', false);
  assert.equal(typeof html, 'string');
  assert.ok(html.includes('boneyard-bone'), 'has bone class');
  assert.ok(html.includes('height:120px'), 'container height reflects skel.height');
  assert.ok(html.includes('background-color:#e8e0d6'), 'uses provided bone color');
});

test('animate:false emits no <style>/keyframes; animate:true does', () => {
  assert.ok(!renderBones(fixture, '#e8e0d6', false).includes('<style>'));
  assert.ok(renderBones(fixture, '#e8e0d6', true).includes('@keyframes boneyard-pulse'));
});

test('container bones (c:true) are not rendered as divs', () => {
  const html = renderBones(fixture, '#e8e0d6', false);
  const count = (html.match(/boneyard-bone/g) || []).length;
  assert.equal(count, 2, 'only the two leaf bones render');
});

test('resolveResponsive picks the nearest breakpoint at or below width', () => {
  const responsive = {
    breakpoints: {
      375: { width: 375, height: 100, bones: [{ x: 0, y: 0, w: 100, h: 20, r: 4 }] },
      768: { width: 768, height: 110, bones: [{ x: 0, y: 0, w: 100, h: 20, r: 4 }] },
      1280: { width: 1280, height: 120, bones: [{ x: 0, y: 0, w: 100, h: 20, r: 4 }] },
    },
  };
  assert.equal(resolveResponsive(responsive, 900).width, 768);
  assert.equal(resolveResponsive(responsive, 1280).width, 1280);
  assert.equal(resolveResponsive(responsive, 320).width, 375, 'below smallest -> smallest');
  // A plain (non-responsive) result is returned unchanged.
  assert.equal(resolveResponsive(fixture, 500), fixture);
});

test('registerBones / getRegisteredBones round-trip', () => {
  registerBones({ 'menu-card': fixture });
  assert.deepEqual(getRegisteredBones('menu-card'), fixture);
  assert.equal(getRegisteredBones('does-not-exist'), undefined);
});

test('normalizeBone converts the compact tuple form', () => {
  assert.deepEqual(normalizeBone([1, 2, 3, 4, 5]), { x: 1, y: 2, w: 3, h: 4, r: 5, c: undefined });
  const obj = { x: 1, y: 2, w: 3, h: 4, r: 5 };
  assert.equal(normalizeBone(obj), obj);
});
