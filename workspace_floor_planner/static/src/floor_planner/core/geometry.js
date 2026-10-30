/**
 * Pure geometry helpers shared by the editor components.
 *
 * Convention (same as the server): x/y is the top-left corner of the
 * *unrotated* rectangle in logical canvas units; rotation is in degrees,
 * clockwise, around the rectangle's centre.
 */

export const MIN_SIZE = 2;

export function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
}

export function round(value, digits = 2) {
    const f = 10 ** digits;
    return Math.round(value * f) / f;
}

export function normalizeAngle(degrees) {
    let value = degrees % 360;
    if (value < 0) {
        value += 360;
    }
    return value >= 360 ? 0 : round(value, 2);
}

export function snap(value, grid, enabled = true) {
    return enabled && grid > 0 ? Math.round(value / grid) * grid : value;
}

/** Rotate a vector clockwise (screen coordinates, y pointing down). */
export function rotateVector(dx, dy, degrees) {
    const a = (degrees * Math.PI) / 180;
    const cos = Math.cos(a);
    const sin = Math.sin(a);
    return { x: dx * cos - dy * sin, y: dx * sin + dy * cos };
}

export function centerOf(rect) {
    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
}

/** Keep the unrotated rectangle inside the canvas (mirrors server rule). */
export function clampToCanvas(rect, canvasWidth, canvasHeight) {
    const width = clamp(rect.width, MIN_SIZE, canvasWidth);
    const height = clamp(rect.height, MIN_SIZE, canvasHeight);
    return {
        width,
        height,
        x: clamp(rect.x, 0, canvasWidth - width),
        y: clamp(rect.y, 0, canvasHeight - height),
    };
}

/**
 * Resize a (possibly rotated) rect by dragging one of its handles.
 *
 * The pointer delta is converted into the shape's local frame, the dragged
 * edges move, and the opposite edges stay fixed in world space.
 *
 * @param {Object} start  rect at drag start {x, y, width, height, rotation}
 * @param {string} handle one of n, s, e, w, ne, nw, se, sw
 * @param {number} dx     world delta x since drag start
 * @param {number} dy     world delta y since drag start
 * @param {Object} [opts] {grid, snap}
 */
export function resizeRect(start, handle, dx, dy, opts = {}) {
    const local = rotateVector(dx, dy, -start.rotation);
    let left = -start.width / 2;
    let right = start.width / 2;
    let top = -start.height / 2;
    let bottom = start.height / 2;
    if (handle.includes("e")) {
        right = Math.max(right + local.x, left + MIN_SIZE);
    }
    if (handle.includes("w")) {
        left = Math.min(left + local.x, right - MIN_SIZE);
    }
    if (handle.includes("s")) {
        bottom = Math.max(bottom + local.y, top + MIN_SIZE);
    }
    if (handle.includes("n")) {
        top = Math.min(top + local.y, bottom - MIN_SIZE);
    }
    const c0 = centerOf(start);
    // Snapping edges only makes sense when the shape is axis-aligned.
    if (opts.snap && opts.grid && normalizeAngle(start.rotation) === 0) {
        const s = (v, base) => snap(v + base, opts.grid) - base;
        if (handle.includes("e")) {
            right = Math.max(s(right, c0.x), left + MIN_SIZE);
        }
        if (handle.includes("w")) {
            left = Math.min(s(left, c0.x), right - MIN_SIZE);
        }
        if (handle.includes("s")) {
            bottom = Math.max(s(bottom, c0.y), top + MIN_SIZE);
        }
        if (handle.includes("n")) {
            top = Math.min(s(top, c0.y), bottom - MIN_SIZE);
        }
    }
    const width = right - left;
    const height = bottom - top;
    const shift = rotateVector((left + right) / 2, (top + bottom) / 2, start.rotation);
    const cx = c0.x + shift.x;
    const cy = c0.y + shift.y;
    return { x: round(cx - width / 2), y: round(cy - height / 2), width: round(width), height: round(height) };
}

/** Angle (degrees) for the rotation handle, which sits above the shape. */
export function rotationFromPointer(rect, point, step = 1) {
    const c = centerOf(rect);
    const degrees = (Math.atan2(point.y - c.y, point.x - c.x) * 180) / Math.PI + 90;
    return normalizeAngle(Math.round(degrees / step) * step);
}

/** Zoom + pan that shows the whole canvas inside a viewport. */
export function fitView(canvasWidth, canvasHeight, viewportWidth, viewportHeight, margin = 24) {
    const zoom = clamp(
        Math.min((viewportWidth - 2 * margin) / canvasWidth, (viewportHeight - 2 * margin) / canvasHeight),
        0.05,
        8
    );
    return {
        zoom,
        panX: -(viewportWidth / zoom - canvasWidth) / 2,
        panY: -(viewportHeight / zoom - canvasHeight) / 2,
    };
}
