/** Normalize a bone from either format to the object format */
export function normalizeBone(b) {
    if (Array.isArray(b)) {
        if (b.length < 5 || b.length > 6) {
            throw new Error(`Invalid bone format: expected [x,y,w,h,r,c?] but got ${b.length} elements`);
        }
        // Length is validated; narrow to the compact tuple shape.
        const t = b;
        return { x: t[0], y: t[1], w: t[2], h: t[3], r: t[4], c: t[5] || undefined };
    }
    return b;
}
