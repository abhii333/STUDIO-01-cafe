// Registers all bundled skeletons by name so the runtime can look them up.
// Static import => bones are registered synchronously as this module evaluates.
import { registerBones } from '../vendor/boneyard/shared.js';
import { ALL_BONES } from './index.mjs';

registerBones(ALL_BONES);

export const BONE_NAMES = Object.keys(ALL_BONES);
