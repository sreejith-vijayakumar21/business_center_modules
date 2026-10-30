import { Component } from "@odoo/owl";

/** Top bar: save state, undo/redo, zoom and grid toggles. Pure presentation. */
export class Toolbar extends Component {
    static template = "workspace_floor_planner.Toolbar";
    static props = {
        store: Object,
        readonly: Boolean,
        onSave: Function,
        onZoom: Function,
        onFit: Function,
    };

    get zoomPercent() {
        return Math.round(this.props.store.view.zoom * 100);
    }

    toggle(field) {
        this.props.store.setPlanOption(field, !this.props.store.plan[field]);
    }
}
