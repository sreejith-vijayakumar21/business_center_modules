import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { clamp, resizeRect, rotationFromPointer, round, snap } from "../core/geometry";
import { FloorObject } from "./floor_object";

const DRAG_THRESHOLD_PX = 3;
export const MIN_ZOOM = 0.05;
export const MAX_ZOOM = 8;

/**
 * SVG drawing surface: renders the plan and turns pointer gestures into
 * store edits (move, resize, rotate, pan, zoom). It owns no layout data.
 */
export class FloorCanvas extends Component {
    static template = "workspace_floor_planner.FloorCanvas";
    static components = { FloorObject };
    static props = {
        store: Object,
        readonly: Boolean,
        onReady: { type: Function, optional: true },
    };

    setup() {
        this.wrapRef = useRef("wrap");
        this.svgRef = useRef("svg");
        this.viewport = useState({ width: 800, height: 600 });
        this.drag = null;
        onMounted(() => {
            this.resizeObserver = new ResizeObserver(() => this.measure());
            this.resizeObserver.observe(this.wrapRef.el);
            this.measure();
            this.props.onReady?.(this);
        });
        onWillUnmount(() => this.resizeObserver?.disconnect());
    }

    get store() {
        return this.props.store;
    }

    get plan() {
        return this.store.plan;
    }

    get view() {
        return this.store.view;
    }

    measure() {
        const rect = this.wrapRef.el.getBoundingClientRect();
        this.viewport.width = Math.max(rect.width, 50);
        this.viewport.height = Math.max(rect.height, 50);
    }

    get viewBox() {
        const { zoom, panX, panY } = this.view;
        return `${panX} ${panY} ${this.viewport.width / zoom} ${this.viewport.height / zoom}`;
    }

    /** Size in canvas units of something that should look ``px`` on screen. */
    px(px) {
        return px / this.view.zoom;
    }

    get gridPath() {
        const g = this.plan.grid_size;
        return `M ${g} 0 L 0 0 0 ${g}`;
    }

    // ------------------------------------------------------------------
    // Coordinates
    // ------------------------------------------------------------------
    toWorld(ev) {
        const rect = this.svgRef.el.getBoundingClientRect();
        return {
            x: this.view.panX + (ev.clientX - rect.left) / this.view.zoom,
            y: this.view.panY + (ev.clientY - rect.top) / this.view.zoom,
        };
    }

    viewCenter() {
        return {
            x: this.view.panX + this.viewport.width / this.view.zoom / 2,
            y: this.view.panY + this.viewport.height / this.view.zoom / 2,
        };
    }

    zoomAt(factor, screenPoint = null) {
        const rect = this.svgRef.el.getBoundingClientRect();
        const sx = screenPoint ? screenPoint.x - rect.left : this.viewport.width / 2;
        const sy = screenPoint ? screenPoint.y - rect.top : this.viewport.height / 2;
        const oldZoom = this.view.zoom;
        const zoom = clamp(oldZoom * factor, MIN_ZOOM, MAX_ZOOM);
        // Keep the point under the cursor fixed.
        this.view.panX += sx / oldZoom - sx / zoom;
        this.view.panY += sy / oldZoom - sy / zoom;
        this.view.zoom = zoom;
    }

    // ------------------------------------------------------------------
    // Pointer handling
    // ------------------------------------------------------------------
    /** Ctrl/⌘ + wheel (or trackpad pinch) zooms; plain wheel pans. */
    onWheel(ev) {
        ev.preventDefault();
        if (ev.ctrlKey || ev.metaKey) {
            this.zoomAt(Math.exp(-ev.deltaY * 0.002), { x: ev.clientX, y: ev.clientY });
        } else {
            const dx = ev.shiftKey ? ev.deltaY : ev.deltaX;
            const dy = ev.shiftKey ? 0 : ev.deltaY;
            this.view.panX += dx / this.view.zoom;
            this.view.panY += dy / this.view.zoom;
        }
    }

    onPointerDown(ev) {
        if (ev.button !== 0 && ev.button !== 1) {
            return;
        }
        const handleEl = ev.target.closest("[data-handle]");
        const objectEl = ev.target.closest("[data-key]");
        const world = this.toWorld(ev);
        const base = { pointerId: ev.pointerId, startClient: { x: ev.clientX, y: ev.clientY }, startWorld: world, moved: false };

        if (ev.button === 1 || ev.altKey || !objectEl || this.props.readonly && !handleEl) {
            if (objectEl && this.props.readonly && ev.button === 0) {
                this.store.select(objectEl.dataset.key);
            }
            this.drag = { ...base, mode: "pan", startPan: { x: this.view.panX, y: this.view.panY }, clickedEmpty: !objectEl };
        } else {
            const key = objectEl.dataset.key;
            this.store.select(key);
            const obj = this.store.selected;
            const start = { x: obj.x, y: obj.y, width: obj.width, height: obj.height, rotation: obj.rotation };
            const mode = handleEl ? (handleEl.dataset.handle === "rotate" ? "rotate" : "resize") : "move";
            this.drag = { ...base, mode, key, start, handle: handleEl?.dataset.handle };
        }
        this.svgRef.el.setPointerCapture(ev.pointerId);
        ev.preventDefault();
    }

    onPointerMove(ev) {
        const drag = this.drag;
        if (!drag || ev.pointerId !== drag.pointerId) {
            return;
        }
        if (!drag.moved) {
            const dist = Math.hypot(ev.clientX - drag.startClient.x, ev.clientY - drag.startClient.y);
            if (dist < DRAG_THRESHOLD_PX) {
                return;
            }
            drag.moved = true;
            if (drag.mode !== "pan") {
                this.store.checkpoint(); // one undo step per gesture
            }
        }
        if (drag.mode === "pan") {
            this.view.panX = drag.startPan.x - (ev.clientX - drag.startClient.x) / this.view.zoom;
            this.view.panY = drag.startPan.y - (ev.clientY - drag.startClient.y) / this.view.zoom;
            return;
        }
        const world = this.toWorld(ev);
        const dx = world.x - drag.startWorld.x;
        const dy = world.y - drag.startWorld.y;
        const useSnap = this.plan.snap_to_grid && !ev.shiftKey;
        const grid = this.plan.grid_size;
        let patch;
        if (drag.mode === "move") {
            patch = {
                x: round(snap(drag.start.x + dx, grid, useSnap)),
                y: round(snap(drag.start.y + dy, grid, useSnap)),
            };
        } else if (drag.mode === "resize") {
            patch = resizeRect(drag.start, drag.handle, dx, dy, { grid, snap: useSnap });
        } else {
            patch = { rotation: rotationFromPointer(drag.start, world, ev.shiftKey ? 1 : 15) };
        }
        this.store.update(drag.key, patch, { checkpoint: false });
    }

    onPointerUp(ev) {
        const drag = this.drag;
        if (!drag || ev.pointerId !== drag.pointerId) {
            return;
        }
        if (drag.mode === "pan" && !drag.moved && drag.clickedEmpty) {
            this.store.select(null);
        }
        this.drag = null;
        if (this.svgRef.el.hasPointerCapture(ev.pointerId)) {
            this.svgRef.el.releasePointerCapture(ev.pointerId);
        }
    }

}
