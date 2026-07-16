/**
 * Runtime — renders skeleton bones to HTML.
 *
 * Usage:
 *   import { computeLayout, renderBones } from 'boneyard-js'
 *
 *   const skeleton = computeLayout(myDescriptor, containerWidth)
 *   element.innerHTML = renderBones(skeleton)
 */
import type { SkeletonResult } from './types.js';
/**
 * Render bones to an HTML string.
 * Use for SSR, innerHTML, or any HTML-based rendering.
 */
export declare function renderBones(skel: SkeletonResult, color?: string, animate?: boolean): string;
