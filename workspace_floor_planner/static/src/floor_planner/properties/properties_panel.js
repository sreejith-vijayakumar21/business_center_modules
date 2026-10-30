import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { LinkSelector } from "../link_selector/link_selector";

const TYPE_LABELS = {
    private_office: _t("Private Office"),
    dedicated_desk: _t("Dedicated Desk"),
    hot_desk: _t("Hot Desk"),
    meeting_room: _t("Meeting Room"),
    coworking_zone: _t("Coworking Zone"),
    wall: _t("Wall"),
    door: _t("Door"),
    window: _t("Window"),
    column: _t("Column"),
    facility: _t("Facility / Amenity"),
    label: _t("Text Label"),
};

/** Right-hand panel: edit the selected object, or plan settings when nothing is selected. */
export class PropertiesPanel extends Component {
    static template = "workspace_floor_planner.PropertiesPanel";
    static components = { LinkSelector };
    static props = {
        store: Object,
        api: Object,
        readonly: Boolean,
        onDelete: Function,
        onDuplicate: Function,
        onOpenLink: Function,
    };

    get store() {
        return this.props.store;
    }

    get obj() {
        return this.store.selected;
    }

    get planSubtitle() {
        return [this.store.plan.site, this.store.plan.code].filter(Boolean).join(" · ");
    }

    get typeLabel() {
        return TYPE_LABELS[this.obj.object_type] || this.obj.object_type;
    }

    get providers() {
        return this.store.providersFor(this.obj.object_type);
    }

    get isRentable() {
        return this.obj.category === "rentable";
    }

    get status() {
        return this.store.statusOf(this.obj);
    }

    metres(units) {
        const scale = this.store.plan.units_per_meter;
        return scale > 0 ? `${(units / scale).toFixed(2)} m` : "";
    }

    setNumber(field, ev, { integer = false } = {}) {
        const value = integer ? parseInt(ev.target.value, 10) : parseFloat(ev.target.value);
        if (Number.isFinite(value)) {
            this.store.update(this.obj.key, { [field]: value });
        } else {
            ev.target.value = this.obj[field];
        }
    }

    setText(field, ev) {
        this.store.update(this.obj.key, { [field]: ev.target.value });
    }

    setPlanNumber(field, ev) {
        const value = parseInt(ev.target.value, 10);
        if (Number.isFinite(value) && value >= 2 && value <= 500) {
            this.store.setPlanOption(field, value);
        } else {
            ev.target.value = this.store.plan[field];
        }
    }

    onLink(provider, record) {
        this.store.setLink(this.obj.key, provider, record);
    }
}
