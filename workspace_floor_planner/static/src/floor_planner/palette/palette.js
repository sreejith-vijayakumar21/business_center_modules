import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

const GROUPS = [
    { category: "rentable", label: _t("Rentable spaces") },
    { category: "zone", label: _t("Zones") },
    { category: "structure", label: _t("Structure") },
    { category: "facility", label: _t("Amenities") },
    { category: "annotation", label: _t("Annotations") },
];

/** Left-hand palette; presets come from the server (data-driven). */
export class Palette extends Component {
    static template = "workspace_floor_planner.Palette";
    static props = {
        presets: Array,
        onAdd: Function,
        disabled: Boolean,
    };

    setup() {
        this.state = useState({ filter: "" });
    }

    get groups() {
        const filter = this.state.filter.trim().toLowerCase();
        return GROUPS.map((group) => ({
            ...group,
            presets: this.props.presets.filter(
                (p) => p.category === group.category && (!filter || p.name.toLowerCase().includes(filter))
            ),
        })).filter((group) => group.presets.length);
    }

    swatchStyle(preset) {
        return `background:${preset.fill_color};border-color:${preset.border_color};color:${preset.text_color}`;
    }
}
