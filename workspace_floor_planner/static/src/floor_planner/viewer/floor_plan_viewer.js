import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { FloorCanvas } from "../canvas/floor_canvas";
import { FloorPlanApi } from "../core/floor_plan_api";
import { fitView } from "../core/geometry";
import { LayoutStore } from "../core/layout_store";
import { createLinkedRecord } from "../core/create_linked_record";
import { StatusLegend } from "../legend/status_legend";

/**
 * Client action "workspace_floor_planner.viewer": read-only overview of a
 * floor with totals on top and the colour-coded layout below. Reuses the
 * editor's store, API and canvas; it simply never edits.
 */
export class FloorPlanViewer extends Component {
    static template = "workspace_floor_planner.Viewer";
    static components = { Layout, FloorCanvas, StatusLegend };
    static props = { ...standardActionServiceProps };

    setup() {
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        const action = this.props.action;
        this.planId = action.params?.plan_id || action.context?.active_id || this.props.resId;
        this.api = new FloorPlanApi(useService("orm"), this.planId);
        this.state = useState({ store: null, statusLoading: false, statusAt: false });
        this.canvas = null;
        onWillStart(async () => {
            this.state.store = LayoutStore.create(await this.api.load());
            await this.refreshStatuses();
        });
        onMounted(() => {
            const seconds = this.store.plan.status_refresh_interval;
            if (seconds > 0) {
                this.timer = setInterval(() => !document.hidden && this.refreshStatuses(), seconds * 1000);
            }
        });
        onWillUnmount(() => clearInterval(this.timer));
    }

    get store() {
        return this.state.store;
    }

    get plan() {
        return this.store.plan;
    }

    get cards() {
        const s = this.store.summary;
        const palette = this.store.statusPalette;
        const cards = [
            { key: "total", label: _t("Total spaces"), value: s.total || 0, color: false },
            { key: "available", label: palette.available?.name, value: s.available || 0, color: palette.available?.color },
            { key: "occupied", label: palette.occupied?.name, value: s.occupied || 0, color: palette.occupied?.color },
        ];
        if (s.reserved) {
            cards.push({ key: "reserved", label: palette.reserved?.name, value: s.reserved, color: palette.reserved?.color });
        }
        cards.push({ key: "maintenance", label: palette.maintenance?.name, value: s.maintenance || 0, color: palette.maintenance?.color });
        return cards;
    }

    get selected() {
        return this.store.selected;
    }

    get createProviders() {
        const obj = this.selected;
        if (!obj?.id || obj.link_key || !this.plan.can_edit) {
            return [];
        }
        return this.store.providersFor(obj.object_type).filter((p) => p.can_create);
    }

    async createFor(provider) {
        const obj = this.selected;
        await createLinkedRecord({
            api: this.api,
            dialog: this.dialog,
            obj,
            provider,
            onLinked: async () => {
                this.store.load(await this.api.load());
                this.store.select(`id_${obj.id}`);
                await this.refreshStatuses();
            },
        });
    }

    onCanvasReady(canvas) {
        this.canvas = canvas;
        this.fit();
    }

    fit() {
        if (this.canvas) {
            const { width, height } = this.canvas.viewport;
            Object.assign(this.store.view, fitView(this.plan.canvas_width, this.plan.canvas_height, width, height));
        }
    }

    zoom(factor) {
        this.canvas?.zoomAt(factor);
    }

    async refreshStatuses() {
        this.state.statusLoading = true;
        try {
            this.store.setStatuses(await this.api.statuses(this.state.statusAt));
        } finally {
            this.state.statusLoading = false;
        }
    }

    async changeStatusAt(at) {
        this.state.statusAt = at;
        await this.refreshStatuses();
    }

    statusName(obj) {
        return this.store.statusOf(obj).display.name;
    }

    async openSelected() {
        const action = this.selected?.id && (await this.api.openLinkedRecordAction(this.selected.id));
        if (action) {
            await this.actionService.doAction(action);
        } else {
            this.notification.add(_t("You do not have access to this record, or it no longer exists."), {
                type: "warning",
            });
        }
    }

    editLayout() {
        return this.actionService.doAction({
            type: "ir.actions.client",
            tag: "workspace_floor_planner.editor",
            name: _t("Edit layout"),
            params: { plan_id: this.planId },
            context: { active_id: this.planId },
        });
    }
}

registry.category("actions").add("workspace_floor_planner.viewer", FloorPlanViewer);
