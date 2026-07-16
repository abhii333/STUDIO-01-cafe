# Vendored: boneyard-js (core subset)

- **Package:** [`boneyard-js`](https://www.npmjs.com/package/boneyard-js) v1.9.0
- **Repo:** https://github.com/0xGF/boneyard
- **License:** MIT (c) boneyard-js authors
- **Vendored on:** 2026-07-17

## Why vendored (and not `npm install`ed)

This is a no-build, native-ESM static site. Installing `boneyard-js` would pull
in `playwright` (a dependency used only by the package's build CLI), which we do
not need at runtime. Instead we copy the framework-agnostic **core** files and
import them natively in the browser.

## What was copied

Only the browser-safe, self-contained subset from the package's `dist/`:

| File | Exports we use |
| --- | --- |
| `extract.js` | `snapshotBones`, `fromElement` (dev capture) |
| `runtime.js` | `renderBones` (render bones -> HTML) |
| `shared.js` | `registerBones`, `getRegisteredBones`, `resolveResponsive` |
| `responsive.js` | `extractResponsive` (multi-breakpoint dev capture) |
| `types.js` | `normalizeBone` |

`.d.ts` files are included for editor tooling only.

## Deliberately NOT copied

- `index.js` — re-exports from `layout.js`.
- `layout.js` — imports the bare specifier `@chenglou/pretext`, which does not
  resolve under native browser ESM. We don't use the layout-engine path, so we
  import directly from the specific files above instead of the package index.

The copied subset uses only relative imports among these five files and browser
APIs (`getBoundingClientRect`, `getComputedStyle`) — no Node built-ins, no
Playwright, no third-party packages.

## Updating

Re-run:

```bash
cd $(mktemp -d)
npm pack boneyard-js@<version>
tar -xzf boneyard-js-*.tgz
# copy the five files above from package/dist/ into this folder
```

Then re-run the vendor smoke test:

```bash
node --test frontend/tools/tests/vendor.test.mjs
```
