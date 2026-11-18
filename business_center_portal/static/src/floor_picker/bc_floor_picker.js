import { Component, onWillUnmount, useEffect, useExternalListener, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { FloorCanvas } from "@workspace_floor_planner/floor_planner/canvas/floor_canvas";
import { centerOf, fitView } from "@workspace_floor_planner/floor_planner/core/geometry";
import { LayoutStore } from "@workspace_floor_planner/floor_planner/core/layout_store";
import { FloorUnitDetails } from "@workspace_floor_planner/floor_planner/picker/floor_unit_details";
import { pointInRect } from "@workspace_floor_planner/floor_planner/picker/pickability";
import { pickerEvents } from "@business_center_portal/floor_picker/picker_events";
import { pickerKind } from "@business_center_portal/floor_picker/picker_kinds";

const ZOOM_STEP = 1.25;

// Slot states sent by the server, plus two for drawing only.
const FREE = "free";
const BOOKED = "booked";
const CLOSED = "closed";
const SMALL = "small";
const PICKED = "picked";
const OTHER = "other";

function slotPalette() {
    return {
        [FREE]: { code: FREE, name: _t("Free for your time"), color: "#8EDCB0" },
        [PICKED]: { code: PICKED, name: _t("Selected"), color: "#8E9BF5" },
        [BOOKED]: { code: BOOKED, name: _t("Booked for your time"), color: "#F4A6A6" },
        [SMALL]: { code: SMALL, name: _t("Too small for your group"), color: "#F6D9A8" },
        [CLOSED]: { code: CLOSED, name: _t("Not available"), color: "#DCE0E8" },
        [OTHER]: { code: OTHER, name: _t("Not bookable here"), color: "#EEF0F4" },
    };
}

async function getJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) {
        throw new Error(response.statusText);
    }
    return response.json();
}

/**
 * Read-only floor plan of the tenant's centre, for picking one kind of unit
 * (a hot desk, a meeting room, ...) given by the ``kind`` prop. Units of that
 * kind are coloured by the server's state for the chosen slot; every other
 * shape is faded and takes no clicks. Clicking a free unit fills the form.
 *
 * Talks to its form only through pickerEvents(kind); what it picks, where
 * it reads from and what it says come from pickerKind(kind).
 */
export class BcFloorPicker extends Component {
    static template = "business_center_portal.BcFloorPicker";
    static components = { FloorCanvas, FloorUnitDetails };
    static props = { kind: String };

    setup() {
        this.kind = pickerKind(this.props.kind);
        this.events = pickerEvents(this.props.kind);
        this.palette = slotPalette();
        this.state = useState({
            ready: false,
            contractId: false,
            params: {},
            sites: [],
            planId: false,
            store: null,
            slot: {},
            slotError: false,
            details: false,
            detailsLoading: false,
        });
        this.area = useRef("area");
        this.canvas = null;
        this.detailsCache = new Map();
        this.resizeObserver = new ResizeObserver(() => this.fit());

        useExternalListener(document, this.events.options, (ev) => this.onOptions(ev.detail));
        useExternalListener(document, this.events.chosen, (ev) => this.onChosen(ev.detail));
        useEffect(
            () => {
                document.dispatchEvent(new CustomEvent(this.events.ready));
            },
            () => [],
        );
        onWillUnmount(() => this.resizeObserver.disconnect());
        // Re-colour and describe whenever the floor, the selection or the
        // slot states change.
        useEffect(
            () => {
                if (this.state.store) {
                    this.colourBySlot(this.state.store, this.state.slot);
                    this.onSelect();
                }
            },
            () => [this.state.store, this.state.store && this.state.store.selectedKey, this.state.slot],
        );
    }

    // ------------------------------------------------------------------
    // MARK: GETTERS
    // ------------------------------------------------------------------
    get plans() {
        return this.state.sites.flatMap((site) => site.plans);
    }

    get notes() {
        return this.state.sites.filter((site) => site.note).map((site) => site.note);
    }

    get legend() {
        return this.kind.legend.map((code) => ({ code, name: this.palette[code].name, color: this.palette[code].color }));
    }

    get selected() {
        return this.state.store ? this.state.store.selected : null;
    }

    get zoomPercent() {
        return this.state.store ? Math.round(this.state.store.view.zoom * 100) : 100;
    }

    /** A saved shape linked to a unit of this picker's kind. */
    isTarget(obj) {
        return obj.link_key === this.kind.linkKey && Boolean(obj.id);
    }

    slotOf(obj) {
        return this.state.slot[obj.id] || CLOSED;
    }

    get selectedStatus() {
        const obj = this.selected;
        if (!obj || !this.isTarget(obj) || this.state.slotError) {
            return undefined;
        }
        const state = this.slotOf(obj);
        const tone = state === FREE ? "pickable" : state === BOOKED ? "booked" : "unpickable";
        return { label: this.palette[state].name, tone };
    }

    get selectedNote() {
        const obj = this.selected;
        if (!obj || !this.isTarget(obj) || this.state.slotError) {
            return undefined;
        }
        return this.kind.notes[this.slotOf(obj)];
    }

    isPickable(obj) {
        return this.isTarget(obj) && this.slotOf(obj) === FREE;
    }

    /** Everything but this picker's units is drawn faded and ignores clicks. */
    isInert(obj) {
        return !this.isTarget(obj);
    }

    /**
     * Colour this picker's units by the server's slot state (the selected
     * free one stands out), grey every other unit, and let zones count
     * their free units.
     */
    colourBySlot(store, slot) {
        store.statusPalette = { ...store.statusPalette, ...this.palette };
        const objects = {};
        const targets = store.objects.filter((o) => this.isTarget(o));
        for (const unit of targets) {
            const state = slot[unit.id] || CLOSED;
            objects[unit.id] = { status: state === FREE && unit.key === store.selectedKey ? PICKED : state };
        }
        for (const obj of store.objects) {
            if (obj.id && obj.category === "rentable" && !this.isTarget(obj)) {
                objects[obj.id] = { status: OTHER };
            } else if (obj.id && obj.category === "zone") {
                const inside = targets.filter((u) => pointInRect(centerOf(u), obj));
                const available = inside.filter((u) => slot[u.id] === FREE).length;
                objects[obj.id] = { status: available ? FREE : CLOSED, available, total: inside.length };
            }
        }
        store.setStatuses({ objects, summary: {}, at: false, time_dependent: false, computed_at: false });
    }

    // ------------------------------------------------------------------
    // MARK: FORM EVENTS
    // ------------------------------------------------------------------
    async onOptions({ contractId, params, sites }) {
        if (contractId !== this.state.contractId) {
            this.detailsCache.clear();
        }
        Object.assign(this.state, { ready: true, contractId, params: params || {}, sites: sites || [] });
        if (this.plans.some((p) => p.id && p.id === this.state.planId)) {
            await this.loadSlots();
        } else {
            const first = this.plans.find((p) => p.id && p.pickable) || this.plans.find((p) => p.id);
            await this.loadPlan(first ? first.id : false);
        }
    }

    onChosen({ id }) {
        const store = this.state.store;
        const obj = store && store.objects.find((o) => this.isTarget(o) && o.link_res_id === id);
        if (obj && store.selectedKey !== obj.key) {
            store.select(obj.key);
        }
    }

    onSelect() {
        const obj = this.selected;
        this.loadDetails(obj);
        if (obj && this.isPickable(obj)) {
            document.dispatchEvent(new CustomEvent(this.events.picked, { detail: { id: obj.link_res_id } }));
        }
    }

    // ------------------------------------------------------------------
    // MARK: LOADING
    // ------------------------------------------------------------------
    async loadPlan(planId) {
        if (planId && planId === this.state.planId && this.state.store) {
            return;
        }
        this.state.planId = planId;
        this.state.slot = {};
        if (!planId) {
            this.state.store = null;
            return;
        }
        const data = await getJson(`${this.kind.floorUrl(planId)}?contract_id=${this.state.contractId}`);
        // Ignore a floor that arrives after another tab was clicked.
        if (this.state.planId !== planId) {
            return;
        }
        this.state.store = LayoutStore.create(data);
        await this.loadSlots();
    }

    async loadSlots() {
        const planId = this.state.planId;
        if (!planId) {
            return;
        }
        const params = new URLSearchParams({ ...this.state.params, contract_id: this.state.contractId });
        let slot = {};
        let failed = false;
        try {
            slot = await getJson(`${this.kind.slotsUrl(planId)}?${params}`);
        } catch {
            failed = true;
        }
        // Ignore an answer for a floor the member has already left.
        if (this.state.planId === planId) {
            this.state.slot = slot;
            this.state.slotError = failed;
        }
    }

    async loadDetails(obj) {
        if (!obj || !this.isTarget(obj)) {
            this.state.details = false;
            this.state.detailsLoading = false;
            return;
        }
        const id = obj.link_res_id;
        if (this.detailsCache.has(id)) {
            this.state.details = this.detailsCache.get(id);
            this.state.detailsLoading = false;
            return;
        }
        this.state.detailsLoading = true;
        let details = false;
        try {
            details = await getJson(`${this.kind.detailsUrl(id)}?contract_id=${this.state.contractId}`);
            this.detailsCache.set(id, details);
        } catch {
            details = false;
        } finally {
            // Ignore an answer that arrives after another unit was clicked.
            if (this.selected && this.selected.link_res_id === id) {
                this.state.details = details;
                this.state.detailsLoading = false;
            }
        }
    }

    // ------------------------------------------------------------------
    // MARK: CANVAS
    // ------------------------------------------------------------------
    onCanvasReady(canvas) {
        this.canvas = canvas;
        if (this.area.el) {
            this.resizeObserver.observe(this.area.el);
        }
        requestAnimationFrame(() => this.fit());
    }

    fit() {
        const area = this.area.el;
        const store = this.state.store;
        if (!area || !store || !area.clientWidth || !area.clientHeight) {
            return;
        }
        Object.assign(store.view, fitView(
            store.plan.canvas_width, store.plan.canvas_height, area.clientWidth, area.clientHeight));
    }

    zoomIn() {
        this.canvas?.zoomAt(ZOOM_STEP);
    }

    zoomOut() {
        this.canvas?.zoomAt(1 / ZOOM_STEP);
    }
}

registry.category("public_components").add("business_center_portal.BcFloorPicker", BcFloorPicker);
