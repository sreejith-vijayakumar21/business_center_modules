import { Component, onMounted, onWillStart, onWillUnmount, useExternalListener, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { useSetupAction } from "@web/search/action_hook";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { FloorCanvas } from "../canvas/floor_canvas";
import { FloorPlanApi } from "../core/floor_plan_api";
import { fitView } from "../core/geometry";
import { LayoutStore } from "../core/layout_store";
import { createLinkedRecord } from "../core/create_linked_record";
import { StatusLegend } from "../legend/status_legend";
import { Palette } from "../palette/palette";
import { PropertiesPanel } from "../properties/properties_panel";
import { Toolbar } from "../toolbar/toolbar";

/**
 * Client action "workspace_floor_planner.editor".
 *
 * Composes the editor from small components and wires them to the store
 * (state) and the API (server). It holds no drawing logic itself.
 */
export class FloorPlannerEditor extends Component {
    static template = "workspace_floor_planner.Editor";
    static components = { Layout, FloorCanvas, Palette, PropertiesPanel, StatusLegend, Toolbar };
    static props = { ...standardActionServiceProps };

    setup() {
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.actionService = useService("action");
        const action = this.props.action;
        this.planId = action.params?.plan_id || action.context?.active_id || this.props.resId;
        this.api = new FloorPlanApi(useService("orm"), this.planId);
        this.state = useState({ store: null, statusLoading: false, statusAt: false });
        this.canvas = null;

        useSetupAction({
            beforeLeave: () => this.confirmLeave(),
            beforeUnload: (ev) => {
                if (this.store?.dirty) {
                    ev.preventDefault();
                    ev.returnValue = "unsaved";
                }
            },
        });

        // Listen on the document so shortcuts work wherever focus is
        // (e.g. after a panel re-render), except inside dialogs and fields.
        useExternalListener(document, "keydown", (ev) => this.onKeydown(ev));

        onWillStart(async () => {
            this.state.store = LayoutStore.create(await this.api.load());
            await this.refreshStatuses();
        });
        onMounted(() => this.startAutoRefresh());
        onWillUnmount(() => clearInterval(this.refreshTimer));
    }

    get store() {
        return this.state.store;
    }

    get readonly() {
        return !this.store.plan.can_edit;
    }

    // ------------------------------------------------------------------
    // Canvas / view
    // ------------------------------------------------------------------
    onCanvasReady(canvas) {
        this.canvas = canvas;
        this.fit();
    }

    fit() {
        if (!this.canvas) {
            return;
        }
        const { width, height } = this.canvas.viewport;
        Object.assign(this.store.view, fitView(this.store.plan.canvas_width, this.store.plan.canvas_height, width, height));
    }

    zoom(factor) {
        this.canvas?.zoomAt(factor);
    }

    // ------------------------------------------------------------------
    // Editing commands
    // ------------------------------------------------------------------
    addPreset(preset) {
        const center = this.canvas
            ? this.canvas.viewCenter()
            : { x: this.store.plan.canvas_width / 2, y: this.store.plan.canvas_height / 2 };
        this.store.addFromPreset(preset, center);
    }

    deleteSelected() {
        const obj = this.store.selected;
        if (!obj || this.readonly) {
            return;
        }
        const remove = () => this.store.remove(obj.key);
        // Removing a linked unit loses its placement: ask first.
        if (obj.link_key || obj.category === "zone") {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Delete object"),
                body: _t("Delete “%s” from this floor plan? The business record itself is not deleted.", obj.name || obj.object_type),
                confirmLabel: _t("Delete"),
                confirmClass: "btn-danger",
                confirm: remove,
                cancel: () => {},
            });
        } else {
            remove();
        }
    }

    duplicateSelected() {
        if (this.store.selected && !this.readonly) {
            this.store.duplicate(this.store.selectedKey);
        }
    }

    nudge(dx, dy) {
        const obj = this.store.selected;
        if (obj && !this.readonly) {
            this.store.update(obj.key, { x: obj.x + dx, y: obj.y + dy });
        }
    }

    async openLinkedRecord() {
        const obj = this.store.selected;
        if (!obj?.id) {
            return;
        }
        if (this.store.dirty) {
            this.notification.add(_t("Save the layout before opening the linked record."), { type: "warning" });
            return;
        }
        const action = await this.api.openLinkedRecordAction(obj.id);
        if (action) {
            await this.actionService.doAction(action);
        } else {
            this.notification.add(_t("You do not have access to this record, or it no longer exists."), { type: "danger" });
        }
    }

    async createLinkedRecord(provider) {
        const obj = this.store.selected;
        if (!obj?.id || this.readonly) {
            return;
        }
        if (this.store.dirty) {
            this.notification.add(_t("Save the layout before creating the linked record."), { type: "warning" });
            return;
        }
        await createLinkedRecord({
            api: this.api,
            dialog: this.dialog,
            obj,
            provider,
            onLinked: () => this.reloadLayout(obj.id),
        });
    }

    async reloadLayout(selectId) {
        this.store.load(await this.api.load());
        this.store.select(selectId ? `id_${selectId}` : null);
        await this.refreshStatuses();
    }

    onKeydown(ev) {
        const target = ev.target;
        if (
            !this.store ||
            ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
            target.isContentEditable ||
            target.closest?.(".modal, .o_dialog") ||
            document.querySelector(".modal.show, .o_dialog .modal")
        ) {
            return;
        }
        const ctrl = ev.ctrlKey || ev.metaKey;
        const key = ev.key.toLowerCase();
        const step = ev.shiftKey ? this.store.plan.grid_size : 1;
        const handlers = {
            delete: () => this.deleteSelected(),
            backspace: () => this.deleteSelected(),
            escape: () => this.store.select(null),
            arrowleft: () => this.nudge(-step, 0),
            arrowright: () => this.nudge(step, 0),
            arrowup: () => this.nudge(0, -step),
            arrowdown: () => this.nudge(0, step),
        };
        const ctrlHandlers = {
            s: () => this.save(),
            z: () => (ev.shiftKey ? this.store.redo() : this.store.undo()),
            y: () => this.store.redo(),
            d: () => this.duplicateSelected(),
        };
        const handler = ctrl ? ctrlHandlers[key] : handlers[key];
        if (handler && (!this.readonly || key === "escape")) {
            ev.preventDefault();
            handler();
        }
    }

    // ------------------------------------------------------------------
    // Persistence and status
    // ------------------------------------------------------------------
    async save() {
        if (this.readonly || this.store.saving || !this.store.dirty) {
            return true;
        }
        this.store.saving = true;
        try {
            const result = await this.api.save(this.store.serialize());
            this.store.applySaveResult(result);
            this.notification.add(_t("Floor plan saved."), { type: "success" });
            await this.refreshStatuses();
            return true;
        } finally {
            // On error Odoo shows the server's message; local edits are kept.
            this.store.saving = false;
        }
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

    startAutoRefresh() {
        const seconds = this.store.plan.status_refresh_interval;
        if (seconds > 0) {
            // One batched request for the whole plan per interval.
            this.refreshTimer = setInterval(() => {
                if (!document.hidden && !this.state.statusLoading) {
                    this.refreshStatuses();
                }
            }, seconds * 1000);
        }
    }

    confirmLeave() {
        if (!this.store?.dirty) {
            return true;
        }
        // The action service may ask more than once for the same navigation:
        // share one dialog and one answer.
        if (!this.leavePromise) {
            this.leavePromise = new Promise((resolve) => {
                this.dialog.add(
                    ConfirmationDialog,
                    {
                        title: _t("Unsaved changes"),
                        body: _t("This floor plan has unsaved changes."),
                        confirmLabel: _t("Save and leave"),
                        confirm: async () => resolve(await this.save().catch(() => false)),
                        cancelLabel: _t("Discard changes"),
                        cancel: () => {
                            // Leaving: later checks in the same navigation must not ask again.
                            this.store.dirty = false;
                            resolve(true);
                        },
                        dismiss: () => resolve(false),
                    },
                    { onClose: () => resolve(false) }
                );
            }).finally(() => {
                this.leavePromise = null;
            });
        }
        return this.leavePromise;
    }
}

registry.category("actions").add("workspace_floor_planner.editor", FloorPlannerEditor);
