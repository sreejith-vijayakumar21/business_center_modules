import { Component, onMounted, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { FloorCanvas } from "../canvas/floor_canvas";
import { FloorPlanApi } from "../core/floor_plan_api";
import { centerOf, fitView, rotateVector } from "../core/geometry";
import { LayoutStore } from "../core/layout_store";

const PICKABLE = "pickable";
const ZOOM_STEP = 1.25;
const UNPICKABLE = "unpickable";
const PICKED = "picked";
const CHOSEN = "chosen";

/** True when ``point`` lies inside ``rect`` once the rect is rotated around its centre. */
function pointInRect(point, rect) {
    const c = centerOf(rect);
    const local = rotateVector(point.x - c.x, point.y - c.y, -(rect.rotation || 0));
    return Math.abs(local.x) <= rect.width / 2 && Math.abs(local.y) <= rect.height / 2;
}

/**
 * Pick a linked record from a floor plan instead of a dropdown.
 *
 * Generic on purpose: the caller says which sites and plans to show and
 * which records may be picked (``allowed``, per link key); the dialog never
 * decides availability itself. Shapes are coloured "pickable" or not, zones
 * summarise the pickable units inside them, and Select hands the chosen
 * record back through ``onPick``.
 */
export class FloorPickerDialog extends Component {
    static template = "workspace_floor_planner.FloorPickerDialog";
    static components = { Dialog, FloorCanvas };
    static props = {
        title: String,
        // [{id, name, note?, plans: [{key, id, name, pickable}]}]; a plan
        // without id is a floor that has no layout yet (listed, not openable)
        sites: Array,
        siteId: { type: Number, optional: true },
        // {link_key: [res_id, ...]}
        allowed: Object,
        // {link_key: [res_id, ...]} already chosen elsewhere (shown, not pickable)
        chosen: { type: Object, optional: true },
        // ({link_key, res_id, name}) => void
        onPick: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        const site = this.props.sites.find((s) => s.id === this.props.siteId) || this.props.sites[0];
        this.state = useState({
            siteId: site ? site.id : false,
            planId: this.firstPlanId(site),
            store: null,
            loading: false,
        });
        this.canvas = null;
        this.canvasArea = useRef("canvasArea");
        onWillStart(() => this.loadPlan());
        // The plan area only gets its real size once the dialog has opened,
        // and changes with the window: fit whenever that size changes.
        onMounted(() => {
            this.resizeObserver = new ResizeObserver(() => this.fit());
            this.resizeObserver.observe(this.canvasArea.el);
        });
        onWillUnmount(() => this.resizeObserver?.disconnect());
        // Re-colour the plan whenever the selection changes, so the picked
        // unit stands out from the other available ones.
        useEffect(
            () => {
                if (this.state.store) {
                    this.applyPickability(this.state.store);
                }
            },
            () => [this.state.store, this.state.store && this.state.store.selectedKey],
        );
    }

    // ------------------------------------------------------------------
    // Getters
    // ------------------------------------------------------------------
    get site() {
        return this.props.sites.find((s) => s.id === this.state.siteId) || null;
    }

    get plans() {
        return this.site ? this.site.plans : [];
    }

    get selected() {
        return this.state.store ? this.state.store.selected : null;
    }

    get selectedPickable() {
        return Boolean(this.selected && this.isPickable(this.selected));
    }

    // ------------------------------------------------------------------
    // Loading
    // ------------------------------------------------------------------
    /** The first floor with something to pick, else the first floor with a layout. */
    firstPlanId(site) {
        if (!site) {
            return false;
        }
        const plan = site.plans.find((p) => p.id && p.pickable) || site.plans.find((p) => p.id);
        return plan ? plan.id : false;
    }

    async loadPlan() {
        if (!this.state.planId) {
            this.state.store = null;
            return;
        }
        this.state.loading = true;
        try {
            const api = new FloorPlanApi(this.orm, this.state.planId);
            const store = LayoutStore.create(await api.load());
            this.applyPickability(store);
            this.state.store = store;
        } finally {
            this.state.loading = false;
        }
    }

    /** Colour every unit by whether it may be picked (the selected one
     * stands out), and summarise zones. */
    applyPickability(store) {
        const palette = store.statusPalette;
        store.statusPalette = {
            ...palette,
            [PICKABLE]: {
                code: PICKABLE,
                name: _t("Available to pick"),
                color: palette.available ? palette.available.color : "#8EDCB0",
            },
            [UNPICKABLE]: { code: UNPICKABLE, name: _t("Not available here"), color: "#DCE0E8" },
            [PICKED]: { code: PICKED, name: _t("Selected"), color: "#8E9BF5" },
            [CHOSEN]: { code: CHOSEN, name: _t("On this contract"), color: "#C9D6FB" },
        };
        const selectedKey = store.selectedKey;
        const objects = {};
        const units = store.objects.filter((o) => o.category === "rentable");
        for (const unit of units) {
            let status = UNPICKABLE;
            if (this.isChosen(unit)) {
                status = CHOSEN;
            } else if (this.isPickable(unit)) {
                status = unit.key === selectedKey ? PICKED : PICKABLE;
            }
            objects[unit.id] = { status };
        }
        for (const zone of store.objects.filter((o) => o.category === "zone")) {
            const inside = units.filter((u) => pointInRect(centerOf(u), zone));
            const available = inside.filter((u) => this.isPickable(u)).length;
            objects[zone.id] = {
                status: available ? PICKABLE : UNPICKABLE,
                available,
                total: inside.length,
            };
        }
        store.setStatuses({ objects, summary: {}, at: false, time_dependent: false, computed_at: false });
    }

    isPickable(obj) {
        const ids = (obj.link_key && this.props.allowed[obj.link_key]) || [];
        return ids.includes(obj.link_res_id);
    }

    isChosen(obj) {
        const ids = (obj.link_key && this.props.chosen && this.props.chosen[obj.link_key]) || [];
        return ids.includes(obj.link_res_id);
    }

    // ------------------------------------------------------------------
    // Canvas
    // ------------------------------------------------------------------
    get zoomPercent() {
        return this.state.store ? Math.round(this.state.store.view.zoom * 100) : 100;
    }

    onCanvasReady(canvas) {
        this.canvas = canvas;
        // A new floor's canvas: fit it once it has been laid out.
        requestAnimationFrame(() => this.fit());
    }

    /**
     * Zoom and pan so the whole floor is visible.
     *
     * Measured on the plan area itself rather than taken from the canvas,
     * which records its size when it mounts: inside a dialog that is still
     * opening, that size is zero and the floor would stay at 100%.
     */
    fit() {
        const area = this.canvasArea.el;
        if (!area || !this.state.store) {
            return;
        }
        const width = area.clientWidth;
        const height = area.clientHeight;
        if (!width || !height) {
            return;
        }
        const plan = this.state.store.plan;
        Object.assign(this.state.store.view, fitView(plan.canvas_width, plan.canvas_height, width, height));
    }

    zoomIn() {
        this.canvas?.zoomAt(ZOOM_STEP);
    }

    zoomOut() {
        this.canvas?.zoomAt(1 / ZOOM_STEP);
    }

    // ------------------------------------------------------------------
    // User actions
    // ------------------------------------------------------------------
    async onSiteChange(ev) {
        this.state.siteId = parseInt(ev.target.value, 10);
        this.state.planId = this.firstPlanId(this.site);
        await this.loadPlan();
    }

    async onPlanClick(planId) {
        if (planId && planId !== this.state.planId) {
            this.state.planId = planId;
            await this.loadPlan();
        }
    }

    confirm() {
        const obj = this.selected;
        if (!obj || !this.isPickable(obj)) {
            return;
        }
        this.props.onPick({
            link_key: obj.link_key,
            res_id: obj.link_res_id,
            name: obj.link_name || obj.name,
        });
        this.props.close();
    }
}
