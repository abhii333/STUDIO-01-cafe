/*
 * Skeleton runtime — window.Skeletons.fill() / .clear().
 *
 * fill(containerId, name, count, opts?)
 *   Renders `count` pixel-matched skeleton cards (bones captured from the real
 *   DOM) into the container, picking the layout variant for the current
 *   viewport width. Only injects into an empty container unless opts.force.
 * clear(containerId)
 *   Removes skeletons this runtime injected and drops aria-busy.
 *
 * The bones themselves are registered by ./bones/registry.mjs (side-effect
 * import below), so they are available synchronously once this module loads.
 */
import { renderBones } from './vendor/boneyard/runtime.js';
import { resolveResponsive, getRegisteredBones } from './vendor/boneyard/shared.js';
import './bones/registry.mjs';

const DEFAULT_COLOR = '#e6ddd2';
const MAX_CARDS = 12;

/** Clamp a requested card count to a sane range. Pure — unit tested. */
export function clampCount(requested, max = MAX_CARDS) {
  let n = parseInt(requested, 10);
  if (!Number.isFinite(n) || n < 1) n = 1;
  return Math.min(n, max);
}

function boneColor() {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue('--sk-bone').trim();
    return v || DEFAULT_COLOR;
  } catch (e) { return DEFAULT_COLOR; }
}

function viewportWidth() {
  return (typeof window !== 'undefined' && window.innerWidth) || 1280;
}

export function fill(containerId, name, count, opts) {
  opts = opts || {};
  const el = document.getElementById(containerId);
  if (!el) return;

  const responsive = getRegisteredBones(name);
  if (!responsive) return; // unknown component — fail safe, leave container as-is

  // Only replace an EMPTY container (or one that currently holds skeletons), so
  // we never clobber real content. We detect skeletons by actual .sk-item
  // children (not just the attribute) so a render that overwrote innerHTML
  // directly can't be mistaken for "still a skeleton". opts.force overrides.
  const alreadySkeleton = el.querySelector(':scope > .sk-item') !== null;
  const hasRealContent = el.children.length > 0 && !alreadySkeleton;
  if (hasRealContent && !opts.force) return;

  const skel = resolveResponsive(responsive, viewportWidth());
  if (!skel) return;

  const n = clampCount(count);
  const color = boneColor();
  const one = renderBones(skel, color, false); // animate via CSS, not inline <style>
  let html = '';
  for (let i = 0; i < n; i++) {
    html += `<div class="sk-item" role="presentation" aria-hidden="true">${one}</div>`;
  }
  el.setAttribute('data-skeleton', '');
  el.setAttribute('aria-busy', 'true');
  el.innerHTML = html;
}

export function clear(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  // Empty the container only if it still holds skeletons. If real content has
  // already replaced them, we just drop the loading markers (never nuke data).
  const hasSkeleton = el.querySelector(':scope > .sk-item') !== null;
  if (hasSkeleton) el.innerHTML = '';
  el.removeAttribute('data-skeleton');
  el.removeAttribute('aria-busy');
}

// Install the real API and flush anything the boot stub queued.
if (typeof window !== 'undefined') {
  const prev = window.Skeletons;
  window.Skeletons = { fill, clear, clampCount, __ready: true };
  if (prev && Array.isArray(prev.__queue)) {
    for (const [method, args] of prev.__queue) {
      try {
        if (typeof window.Skeletons[method] === 'function') {
          window.Skeletons[method].apply(null, args);
        }
      } catch (e) { /* ignore a bad queued call */ }
    }
  }
}
