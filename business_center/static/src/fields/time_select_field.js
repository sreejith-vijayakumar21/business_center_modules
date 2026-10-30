import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const EPSILON = 1e-6;

/** 13.5 -> "1:30 PM", like the server's _float_to_ampm. */
function toAmPm(value) {
    const total = Math.round(value * 60);
    const hours = Math.floor(total / 60);
    const minutes = total % 60;
    const period = hours % 24 < 12 ? "AM" : "PM";
    const displayHour = hours % 12 || 12;
    return `${displayHour}:${String(minutes).padStart(2, "0")} ${period}`;
}

/**
 * Pick a booking time from a 12-hour list instead of typing a 24-hour value.
 *
 * Offers every step (30 min by default) inside the room's opening hours.
 * Start times inside a confirmed booking are disabled; end times are
 * disabled when they are not after the start, exceed the 8-hour limit, or
 * would run into another booking. The server constraints still decide.
 *
 * Options: role ("start" | "end"), step (minutes), open_field, close_field,
 * busy_field (list of [start, end] pairs), start_field (for the end time),
 * end_field (for the start time, cleared when no longer after the start).
 */
export class BcTimeSelectField extends Component {
    static template = "business_center.TimeSelectField";
    static props = {
        ...standardFieldProps,
        role: { type: String, optional: true },
        step: { type: Number, optional: true },
        openField: { type: String, optional: true },
        closeField: { type: String, optional: true },
        busyField: { type: String, optional: true },
        startField: { type: String, optional: true },
        endField: { type: String, optional: true },
    };

    get data() {
        return this.props.record.data;
    }

    get value() {
        return this.data[this.props.name] || 0;
    }

    get isEnd() {
        return this.props.role === "end";
    }

    get displayValue() {
        return this.value ? toAmPm(this.value) : "";
    }

    get busy() {
        return (this.props.busyField && this.data[this.props.busyField]) || [];
    }

    get options() {
        const open = (this.props.openField && this.data[this.props.openField]) || 0;
        const close = (this.props.closeField && this.data[this.props.closeField]) || 24;
        const step = (this.props.step || 30) / 60;
        const start = (this.props.startField && this.data[this.props.startField]) || 0;
        const options = [];
        for (let t = open; t <= close + EPSILON; t += step) {
            const time = Math.round(t * 1000) / 1000;
            if (!this.isEnd && time >= close - EPSILON) {
                break; // nothing can start at closing time
            }
            if (this.isEnd && time <= open + EPSILON) {
                continue; // nothing can end at opening time
            }
            options.push({ value: time, label: toAmPm(time), disabled: this.isBlocked(time, start) });
        }
        return options;
    }

    isBlocked(time, start) {
        if (!this.isEnd) {
            return this.busy.some(([s, e]) => time >= s - EPSILON && time < e - EPSILON);
        }
        if (!start) {
            return false;
        }
        return (
            time <= start + EPSILON ||
            this.busy.some(([s, e]) => s < time - EPSILON && e > start + EPSILON)
        );
    }

    isSelected(option) {
        return Math.abs(option.value - this.value) < EPSILON;
    }

    get hasSelection() {
        return this.options.some((o) => this.isSelected(o));
    }

    async onChange(ev) {
        const value = parseFloat(ev.target.value) || 0;
        const changes = { [this.props.name]: value };
        // A new start time can leave the end time before it: clear it.
        const endField = this.props.endField;
        if (!this.isEnd && endField && this.data[endField] && this.data[endField] <= value + EPSILON) {
            changes[endField] = 0;
        }
        await this.props.record.update(changes);
    }
}

registry.category("fields").add("bc_time_select", {
    component: BcTimeSelectField,
    displayName: _t("Time (12-hour list)"),
    supportedTypes: ["float"],
    extractProps: ({ options }) => ({
        role: options.role,
        step: options.step,
        openField: options.open_field,
        closeField: options.close_field,
        busyField: options.busy_field,
        startField: options.start_field,
        endField: options.end_field,
    }),
});
