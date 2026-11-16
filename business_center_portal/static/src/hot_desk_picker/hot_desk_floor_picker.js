import { Component, onWillUnmount, useEffect, useExternalListener, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { FloorCanvas } from "@workspace_floor_planner/floor_planner/canvas/floor_canvas";
import { fitView } from "@workspace_floor_planner/floor_planner/core/geometry";
import { LayoutStore } from "@workspace_floor_planner/floor_planner/core/layout_store";
import { FloorUnitDetails } from "@workspace_floor_planner/floor_planner/picker/floor_unit_details";
import { colourByPickability } from "@workspace_floor_planner/floor_planner/picker/pickability";
import { HOT_DESK_EVENTS } from "@business_center_portal/js/hot_desk_events";

const LINK_KEY = "bc_hot_desk";

async function getJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) {
        throw new Error(response.statusText);
    }
    return response.json();
}

/**
 * Read-only floor plan of the tenant's centre: free hot desks for the chosen
 * slot are green; clicking one fills the booking form. Talks to the form
 * only through HOT_DESK_EVENTS; availability always comes from the server.
 */
export class HotDeskFloorPicker extends Component {
    static template = "business_center_portal.HotDeskFloorPicker";
    static components = { FloorCanvas, FloorUnitDetails };
    static props = {};

    setup() {
        this.state = useState({
            ready: false,
            contractId: false,
            sites: [],
            allowed: [],
            planId: false,
            store: null,
            details: false,
            detailsLoading: false,
            version: 0,
        });
        this.area = useRef("area");
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
        // free desks change.
        useEffect(
            () => {
                if (this.state.store) {
                    colourByPickability(this.state.store, { isPickable: (o) => this.isPickable(o) });
                    this.onSelect();
                }
            },
            () => [this.state.store, this.state.store && this.state.store.selectedKey, this.state.version],
        );
    }

    // ------------------------------------------------------------------
    // MARK: GETTERS
    // ------------------------------------------------------------------
    get plans() {
        return this.state.sites.flatMap((site) => site.plans);
    }

    get selected() {
        return this.state.store ? this.state.store.selected : null;
    }

    get selectedStatus() {
        const obj = this.selected;
        if (!obj || obj.category !== "rentable") {
            return undefined;
        }
        return this.isPickable(obj)
            ? { label: _t("Free for your time"), tone: "pickable" }
            : { label: _t("Not available"), tone: "unpickable" };
    }

    get selectedNote() {
        const obj = this.selected;
        if (!obj || !obj.link_key || obj.link_key === LINK_KEY) {
            return undefined;
        }
        return _t("Only hot desks can be booked here.");
    }

    isPickable(obj) {
        return obj.link_key === LINK_KEY && this.state.allowed.includes(obj.link_res_id);
    }

    // ------------------------------------------------------------------
    // MARK: FORM EVENTS
    // ------------------------------------------------------------------
    async onOptions({ contractId, desks, sites }) {
        if (contractId !== this.state.contractId) {
            this.detailsCache.clear();
        }
        Object.assign(this.state, {
            ready: true,
            contractId,
            allowed: desks,
            sites,
            version: this.state.version + 1,
        });
        if (!this.plans.some((p) => p.id && p.id === this.state.planId)) {
            const first = this.plans.find((p) => p.id && p.pickable) || this.plans.find((p) => p.id);
            await this.loadPlan(first ? first.id : false);
        }
    }

    onChosen({ id }) {
        const store = this.state.store;
        const obj = store && store.objects.find((o) => o.link_key === LINK_KEY && o.link_res_id === id);
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
        this.state.planId = planId;
        if (!planId) {
            this.state.store = null;
            return;
        }
        const data = await getJson(`/my/hot-desks/floor/${planId}?contract_id=${this.state.contractId}`);
        this.state.store = LayoutStore.create(data);
    }

    async loadDetails(obj) {
        if (!obj || obj.link_key !== LINK_KEY) {
            this.state.details = false;
            this.state.detailsLoading = false;
            return;
        }
        const id = obj.link_res_id;
        if (this.detailsCache.has(id)) {
            this.state.details = this.detailsCache.get(id);
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
    onCanvasReady() {
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
}

registry.category("public_components").add("business_center_portal.HotDeskFloorPicker", HotDeskFloorPicker);