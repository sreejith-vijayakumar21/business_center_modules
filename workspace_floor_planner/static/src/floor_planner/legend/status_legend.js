import { Component } from "@odoo/owl";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";

/** Legend + counts + status time context. Colour is always paired with text. */
export class StatusLegend extends Component {
    static template = "workspace_floor_planner.StatusLegend";
    static props = {
        store: Object,
        loading: Boolean,
        onRefresh: Function,
        onChangeAt: Function,
    };

    get counts() {
        const counts = {};
        for (const o of this.props.store.objects) {
            if (o.category === "rentable") {
                const code = this.props.store.statusOf(o).status;
                counts[code] = (counts[code] || 0) + 1;
            }
        }
        return counts;
    }

    get computedAt() {
        const value = this.props.store.statusMeta.computedAt;
        return value ? formatDateTime(deserializeDateTime(value)) : "";
    }

    onAtChange(ev) {
        // datetime-local gives local time; the server expects UTC.
        const value = ev.target.value;
        this.props.onChangeAt(value ? new Date(value).toISOString().slice(0, 19).replace("T", " ") : false);
    }
}
