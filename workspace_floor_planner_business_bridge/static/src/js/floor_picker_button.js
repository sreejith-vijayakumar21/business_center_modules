import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { FloorPickerDialog } from "@workspace_floor_planner/floor_planner/picker/floor_picker_dialog";

/**
 * "Pick from floor plan" button.
 *
 * Shows the records a many2one may take on their floor layouts and fills it
 * with the one picked. Configured by the view, so any form can use it:
 *   field          the many2one to fill
 *   options_field  x2many listing the records that may be picked
 *   link_key       floor planner link key of those records
 *   title          dialog title
 *   chosen_fields  {link_key: x2many} of records already chosen elsewhere
 */
export class BcFloorPickerButton extends Component {
    static template = "workspace_floor_planner_business_bridge.FloorPickerButton";
    static props = {
        ...standardWidgetProps,
        field: String,
        optionsField: String,
        linkKey: String,
        title: { type: String, optional: true },
        chosenFields: { type: Object, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
    }

    get disabled() {
        return Boolean(this.props.readonly);
    }

    /** Records already chosen elsewhere, per link key, shown but not pickable. */
    get chosen() {
        const data = this.props.record.data;
        return Object.fromEntries(
            Object.entries(this.props.chosenFields || {}).map(
                ([linkKey, fieldName]) => [linkKey, data[fieldName]?.currentIds || []]
            )
        );
    }

    async open() {
        const record = this.props.record;
        const resIds = record.data[this.props.optionsField].currentIds;
        if (!resIds.length) {
            this.notification.add(_t("Nothing is available to pick right now."), { type: "warning" });
            return;
        }
        const sites = await this.orm.call(
            "business.center.floor", "bc_get_picker_sites", [this.props.linkKey, resIds]);
        if (!sites.length) {
            this.notification.add(
                _t("None of the available units are drawn on a floor layout yet. Use the dropdown instead."),
                { type: "warning" });
            return;
        }
        this.dialog.add(FloorPickerDialog, {
            title: this.props.title || _t("Pick from the floor plan"),
            sites,
            siteId: (sites.find((s) => s.plans.some((p) => p.pickable)) || sites[0]).id,
            allowed: { [this.props.linkKey]: resIds },
            chosen: this.chosen,
            onPick: (pick) => record.update({
                [this.props.field]: { id: pick.res_id, display_name: pick.name },
            }),
        });
    }
}

registry.category("view_widgets").add("bc_floor_picker", {
    component: BcFloorPickerButton,
    extractProps: ({ options }) => ({
        field: options.field,
        optionsField: options.options_field,
        linkKey: options.link_key,
        title: options.title,
        chosenFields: options.chosen_fields,
    }),
});