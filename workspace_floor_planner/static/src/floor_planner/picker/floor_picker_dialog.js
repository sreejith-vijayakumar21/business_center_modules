import { Component, onMounted, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { FloorCanvas } from "../canvas/floor_canvas";
import { FloorPlanApi } from "../core/floor_plan_api";
import { fitView } from "../core/geometry";
import { LayoutStore } from "../core/layout_store";
import { FloorUnitDetails } from "./floor_unit_details";
import { colourByPickability } from "./pickability";

const ZOOM_STEP = 1.25;


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
    static components = { Dialog, FloorCanvas, FloorUnitDetails };
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
        // {link_key: text} explaining why units of that kind cannot be
        // picked here, shown in the details panel
        notes: { type: Object, optional: true },
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
            details: false,
            detailsLoading: false,
        });
        this.canvas = null;
        this.api = null;
        // Details per object id, so clicking back and forth costs one call.
        this.detailsCache = new Map();
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
        // Load the details of whichever unit is selected.
        useEffect(
            () => {
                this.loadDetails(this.selected);
            },
            () => [this.state.store, this.state.store && this.state.store.selectedKey],
        );
    }

    // ------------------------------------------------------------------
    // MARK: Getters
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

    /** Why the selected unit can or cannot be picked, for the side panel. */
    get selectedStatus() {
        const obj = this.selected;
        if (!obj || obj.category !== "rentable") {
            return undefined;
        }
        if (this.isChosen(obj)) {
            return { label: _t("On this contract"), tone: "chosen" };
        }
        if (this.isPickable(obj)) {
            return { label: _t("Available to pick"), tone: "pickable" };
        }
        return { label: _t("Not available here"), tone: "unpickable" };
    }

    /** The caller's explanation for a unit that cannot be picked here. */
    get selectedNote() {
        const obj = this.selected;
        if (!obj || !obj.link_key || this.isPickable(obj) || this.isChosen(obj)) {
            return undefined;
        }
        return (this.props.notes || {})[obj.link_key];
    }

    // ------------------------------------------------------------------
    // MARK: LOADING
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
            this.api = new FloorPlanApi(this.orm, this.state.planId);
            const store = LayoutStore.create(await this.api.load());
            this.applyPickability(store);
            this.state.store = store;
        } finally {
            this.state.loading = false;
        }
    }

    /** Colour every unit by whether it may be picked (the selected one
     * stands out), and summarise zones. */
    applyPickability(store) {
        colourByPickability(store, {
            isPickable: (obj) => this.isPickable(obj),
            isChosen: (obj) => this.isChosen(obj),
        });
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
    // MARK: Details
    // ------------------------------------------------------------------
    /** Saved, linked units and zones have a record to describe. */
    hasDetails(obj) {
        return Boolean(obj && obj.id && obj.link_key && ["rentable", "zone"].includes(obj.category));
    }

    async loadDetails(obj) {
        if (!this.hasDetails(obj)) {
            this.state.details = false;
            this.state.detailsLoading = false;
            return;
        }
        if (this.detailsCache.has(obj.id)) {
            this.state.details = this.detailsCache.get(obj.id);
            this.state.detailsLoading = false;
            return;
        }
        this.state.detailsLoading = true;
        let details = false;
        try {
            details = await this.api.unitDetails(obj.id);
            this.detailsCache.set(obj.id, details);
        } finally {
            // Ignore an answer that arrives after another unit was clicked.
            if (this.selected && this.selected.id === obj.id) {
                this.state.details = details;
                this.state.detailsLoading = false;
            }
        }
    }

    // ------------------------------------------------------------------
    // MARK: Canvas
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
