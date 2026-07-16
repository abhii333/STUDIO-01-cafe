import type { ResponsiveDescriptor } from './types.js';
/**
 * Extract a responsive descriptor from a rendered DOM element at multiple widths.
 *
 * Resizes the element's container to each breakpoint width, extracts the
 * skeleton descriptor, and returns a ResponsiveDescriptor mapping.
 *
 * Use this at build time, in a test, or in a dev tool to pre-generate
 * descriptors that work at every breakpoint. Ship the result as JSON.
 *
 * @example Browser dev tool / test:
 * ```ts
 * import { extractResponsive } from 'boneyard-js'
 *
 * // Render your component, then:
 * const el = document.querySelector('.blog-post')!
 * const descriptor = extractResponsive(el, [0, 768, 1024])
 * console.log(JSON.stringify(descriptor, null, 2))
 * // Save as blog-post-skeleton.json
 * ```
 *
 * @example Playwright / build script:
 * ```ts
 * for (const width of [375, 768, 1280]) {
 *   await page.setViewportSize({ width, height: 800 })
 *   await page.waitForTimeout(100)
 *   const desc = await page.evaluate(() => {
 *     const { extractResponsive } = require('boneyard')
 *     return extractResponsive(document.querySelector('.card')!)
 *   })
 * }
 * ```
 */
export declare function extractResponsive(el: Element, breakpoints?: number[]): ResponsiveDescriptor;
