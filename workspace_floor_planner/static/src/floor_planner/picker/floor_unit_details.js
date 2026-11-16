import { Component } from "@odoo/owl";

/**
 * Side panel describing the clicked unit. Renders what the link provider
 * returned; it knows nothing about the business records themselves. Used by
 * the backend floor picker dialog and by the tenant portal.
 */
export class FloorUnitDetails extends Component {
    static template = "workspace_floor_planner.FloorUnitDetails";
    static props = {
        // provider details, or false when the unit has none
        details: [Object, Boolean],
        loading: Boolean,
        // whether any shape is selected, to pick the empty-state text
        selected: Boolean,
        // {label, tone}; tone is "pickable", "chosen" or "unpickable"
        status: { type: Object, optional: true },
        // why the unit cannot be picked here, as given by the caller
        note: { type: String, optional: true },
    };
}