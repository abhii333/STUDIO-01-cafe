import type { ResponsiveBones, SkeletonResult } from './types.js';
export type RegisteredBones = SkeletonResult | ResponsiveBones;
export declare function registerBones(map: Record<string, RegisteredBones>): void;
export declare function getRegisteredBones(name: string): RegisteredBones | undefined;
export declare function ensureBuildSnapshotHook(): void;
export declare function isBuildMode(): boolean;
export declare function resolveResponsive(bones: RegisteredBones, width: number): SkeletonResult | null;
export declare const SHIMMER: {
    readonly angle: 110;
    readonly start: 30;
    readonly end: 70;
    readonly speed: "2s";
    readonly lightHighlight: "#f7f7f7";
    readonly darkHighlight: "#2c2c2c";
};
export declare const PULSE: {
    readonly speed: "1.8s";
    /** adjustColor factor for lighter color in pulse animation */
    readonly lightAdjust: 0.3;
    readonly darkAdjust: 0.02;
};
export declare const CONTAINER: {
    readonly adjustment: 0.12;
    readonly darkAdjustment: 0.03;
};
export declare const DEFAULTS: {
    /** Web frameworks: solid opaque bone colors */
    readonly web: {
        readonly light: "#f0f0f0";
        readonly dark: "#222222";
    };
    /** React Native */
    readonly native: {
        readonly light: "#f0f0f0";
        readonly dark: "#222222";
    };
    /** Vanilla runtime (renderBones) */
    readonly runtime: "#f0f0f0";
};
export declare const NATIVE_SHIMMER: {
    /** Duration in ms for one shimmer sweep (aligned with web SHIMMER.speed) */
    readonly speed: 2000;
    /** Width of shimmer highlight as fraction of bone width */
    readonly widthFraction: 0.4;
    /** Opacity of shimmer highlight overlay */
    readonly opacity: 0.6;
};
export declare function adjustColor(color: string, amount: number): string;
