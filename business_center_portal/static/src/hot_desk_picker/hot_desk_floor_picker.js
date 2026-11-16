import { Component, onWillUnmount, useEffect, useExternalListener, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { FloorCanvas } from "@workspace_floor_planner/floor_planner/canvas/floor_canvas";
import { centerOf, fitView } from "@workspace_floor_planner/floor_planner/core/geometry";
import { LayoutStore } from "@workspace_floor_planner/floor_planner/core/layout_store";
import { FloorUnitDetails } from "@workspace_floor_planner/floor_planner/picker/floor_unit_details";
import { pointInRect } from "@workspace_floor_planner/floor_planner/picker/pickability";
import { HOT_DESK_EVENTS } from "@business_center_portal/js/hot_desk_events";

const LINK_KEY = "bc_hot_desk";
const ZOOM_STEP = 1.25;

// Slot states sent by the server, plus two for drawing only.
const FREE = "free";
const BOOKED = "booked";
const CLOSED = "closed";
const PICKED = "picked";
const OTHER = "other";

function slotPalette() {
    return {
        [FREE]: { code: FREE, name: _t("Free for your time"), color: "#8EDCB0" },
        [PICKED]: { code: PICKED, name: _t("Selected"), color: "#8E9BF5" },
        [BOOKED]: { code: BOOKED, name: _t("Booked for your time"), color: "#F4A6A6" },
        [CLOSED]: { code: CLOSED, name: _t("Not open for booking"), color: "#DCE0E8" },
        [OTHER]: { code: OTHER, name: _t("Not bookable here"), color: "#EEF0F4" },
    };
}

/** A saved shape linked to a hot desk. */
function isHotDesk(obj) {
    return obj.link_key === LINK_KEY && Boolean(obj.id);
}

/**
 * Colour hot desks by the server's slot state (the selected free one stands
 * out), grey every other unit, and let zones count their free desks.
 *
 * @param {Object} store a LayoutStore
 * @param {Object} slot {shape id: "free" | "booked" | "closed"}
 */
function colourBySlot(store, slot) {
    store.statusPalette = { ...store.statusPalette, ...slotPalette() };
    const objects = {};
    const desks = store.objects.filter(isHotDesk);
    for (const desk of desks) {
        const state = slot[desk.id] || CLOSED;
        objects[desk.id] = { status: state === FREE && desk.key === store.selectedKey ? PICKED : state };
    }
    for (const obj of store.objects) {
        if (obj.id && obj.category === "rentable" && !isHotDesk(obj)) {
            objects[obj.id] = { status: OTHER };
        } else if (obj.id && obj.category === "zone") {
            const inside = desks.filter((d) => pointInRect(centerOf(d), obj));
            const available = inside.filter((d) => slot[d.id] === FREE).length;
            objects[obj.id] = { status: available ? FREE : CLOSED, available, total: inside.length };
        }
    }
    store.setStatuses({ objects, summary: {}, at: false, time_dependent: false, computed_at: false });
}

async function getJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) {
        throw new Error(response.statusText);
    }
    return response.json();
}

/**
 * Read-only floor plan of the tenant's centre. Hot desks are green when free
 * for the chosen slot, red when booked and grey when closed; every other
 * shape is faded and takes no clicks. Clicking a green desk fills the
 * booking form. Talks to the form only through HOT_DESK_EVENTS, and every
 * slot state comes from the server.
 */
export class HotDeskFloorPicker extends Component {
    static template = "business_center_portal.HotDeskFloorPicker";
    static components = { FloorCanvas, FloorUnitDetails };
    static props = {};

    setup() {
        this.state = useState({
            ready: false,
            contractId: false,
            bookingDate: "",
            startTime: "",
            endTime: "",
            sites: [],
            planId: false,
            store: null,
            slot: {},
            details: false,
            detailsLoading: false,
        });
        this.area = useRef("area");
        this.canvas = null;
        this.detailsCache = new Map();
        this.resizeObserver = new ResizeObserver(() => this.fit());

        useExternalListener(document, HOT_DESK_EVENTS.options, (ev) => this.onOptions(ev.detail));
        useExternalListener(document, HOT_DESK_EVENTS.chosen, (ev) => this.onChosen(ev.detail));
        useEffect(
            () => {
                document.dispatchEvent(new CustomEvent(HOT_DESK_EVENTS.ready));
            },
            () => [],
        );
        onWillUnmount(() => this.resizeObserver.disconnect());
        // Re-colour and describe whenever the floor, the selection or the
        // slot states change.
        useEffect(
            () => {
                if (this.state.store) {
                    colourBySlot(this.state.store, this.state.slot);
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

    get selected() {
        return this.state.store ? this.state.store.selected : null;
    }

    get zoomPercent() {
        return this.state.store ? Math.round(this.state.store.view.zoom * 100) : 100;
    }

    slotOf(obj) {
        return this.state.slot[obj.id] || CLOSED;
    }

    get selectedStatus() {
        const obj = this.selected;
        if (!obj || !isHotDesk(obj)) {
            return undefined;
        }
        const state = this.slotOf(obj);
        if (state === FREE) {
            return { label: _t("Free for your time"), tone: "pickable" };
        }
        if (state === BOOKED) {
            return { label: _t("Booked for your time"), tone: "booked" };
        }
        return { label: _t("Not open for booking"), tone: "unpickable" };
    }

    get selectedNote() {
        const obj = this.selected;
        if (!obj || !isHotDesk(obj)) {
            return undefined;
        }
        const state = this.slotOf(obj);
        if (state === BOOKED) {
            return _t("This desk is taken for part of your time. Pick a green desk or change the time.");
        }
        if (state === CLOSED) {
            return _t("This desk is not open for booking right now.");
        }
        return undefined;
    }

    isPickable(obj) {
        return isHotDesk(obj) && this.slotOf(obj) === FREE;
    }

    /** Everything but hot desks is drawn faded and ignores clicks. */
    isInert(obj) {
        return !isHotDesk(obj);
    }

    // ------------------------------------------------------------------
    // MARK: FORM EVENTS
    // ------------------------------------------------------------------
    async onOptions({ contractId, bookingDate, startTime, endTime, sites }) {
        if (contractId !== this.state.contractId) {
            this.detailsCache.clear();
        }
        Object.assign(this.state, { ready: true, contractId, bookingDate, startTime, endTime, sites });
        if (this.plans.some((p) => p.id && p.id === this.state.planId)) {
            await this.loadSlots();
        } else {
            const first = this.plans.find((p) => p.id && p.pickable) || this.plans.find((p) => p.id);
            await this.loadPlan(first ? first.id : false);
        }
    }

    onChosen({ id }) {
        const store = this.state.store;
        const obj = store && store.objects.find((o) => isHotDesk(o) && o.link_res_id === id);
        if (obj && store.selectedKey !== obj.key) {
            store.select(obj.key);
        }
    }

    onSelect() {
        const obj = this.selected;
        this.loadDetails(obj);
        if (obj && this.isPickable(obj)) {
            document.dispatchEvent(new CustomEvent(HOT_DESK_EVENTS.picked, { detail: { id: obj.link_res_id } }));
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
        const data = await getJson(`/my/hot-desks/floor/${planId}?contract_id=${this.state.contractId}`);
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
        const params = new URLSearchParams({
            contract_id: this.state.contractId,
            booking_date: this.state.bookingDate,
            start_time: this.state.startTime,
            end_time: this.state.endTime,
        });
        const slot = await getJson(`/my/hot-desks/floor/${planId}/slots?${params}`);
        if (this.state.planId === planId) {
            this.state.slot = slot;
        }
    }

    async loadDetails(obj) {
        if (!obj || !isHotDesk(obj)) {
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
            details = await getJson(`/my/hot-desks/desk/${id}?contract_id=${this.state.contractId}`);
            this.detailsCache.set(id, details);
        } catch {
            details = false;
        } finally {
            // Ignore an answer that arrives after another desk was clicked.
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

registry.category("public_components").add("business_center_portal.HotDeskFloorPicker", HotDeskFloorPicker);