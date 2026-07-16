// Bundles js/bones/*.bones.json into js/bones/index.mjs so the runtime can
// statically import all skeletons (instant paint, no extra fetch, no JSON
// import-attribute compatibility concerns). The .bones.json files remain the
// source of truth (produced by the capture harness); this is generated.
//
// Run after re-capturing bones:  node frontend/tools/build-bones-index.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { FIXTURES } from './bone-fixtures.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const bonesDir = path.join(here, '..', 'js', 'bones');

const data = {};
for (const fx of FIXTURES) {
  const file = path.join(bonesDir, `${fx.name}.bones.json`);
  data[fx.name] = JSON.parse(fs.readFileSync(file, 'utf8'));
}

const out =
  '// AUTO-GENERATED from js/bones/*.bones.json by tools/build-bones-index.mjs.\n' +
  '// Do not edit by hand — re-run the generator after re-capturing bones.\n' +
  'export const ALL_BONES = ' + JSON.stringify(data, null, 2) + ';\n';

fs.writeFileSync(path.join(bonesDir, 'index.mjs'), out);
console.log('wrote js/bones/index.mjs with', Object.keys(data).length, 'components');
