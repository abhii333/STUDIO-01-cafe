import type { SkeletonDescriptor, SkeletonResult, SnapshotConfig } from './types.js';
/**
 * Snapshot the exact visual layout of a rendered DOM element as skeleton bones.
 * Walks the DOM, finds every visible leaf element, and captures its exact
 * bounding rect relative to the root. No layout engine, no heuristics —
 * just pixel-perfect positions read directly from the browser.
 *
 *   const { bones, width, height } = snapshotBones(el, 'my-component', config)
 */
export declare function snapshotBones(el: Element, name?: string, config?: SnapshotConfig): SkeletonResult;
/**
 * Extract a SkeletonDescriptor from a rendered DOM element.
 * Reads computed styles — no config needed. Just point it at your component.
 */
export declare function fromElement(el: Element): SkeletonDescriptor;
