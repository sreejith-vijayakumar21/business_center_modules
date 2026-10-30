import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { FloorPickerDialog } from "@workspace_floor_planner/floor_planner/picker/floor_picker_dialog";

/** Per lease asset type: the field to fill, the field listing what may be
 * picked, and the floor planner link key of those records. */
const PICK_CONFIG = {
    office: {
        field: "space_id",
        options: "available_space_ids",
        linkKey: "bc_office",
        title: _t("Pick an office from the floor plan"),
    },
    desk: {
        field: "desk_id",
        options: "available_desk_ids",
        linkKey: "bc_desk",
        title: _t("Pick a desk from the floor plan"),
    },
};

/**
 * "Pick from floor plan" button on a leased asset line.
 *
 * Offers exactly the records the line's own dropdown offers (its
 * available_space_ids / available_desk_ids), shown on their floor layouts,
 * and fills the space or desk field with the one picked.
 */
export class BcFloorPickerButton extends Component {
    static template = "workspace_floor_planner_business_bridge.FloorPickerButton";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
    }

    get config() {
        return PICK_CONFIG[this.props.record.data.lease_asset_type] || null;
    }

    get disabled() {
        return Boolean(this.props.readonly || !this.config);
    }

    async open() {
        const record = this.props.record;
        const config = this.config;
        const resIds = record.data[config.options].currentIds;
        if (!resIds.length) {
            this.notification.add(_t("Nothing is available for this contract's dates."), {
                type: "warning",
            });
            return;
        }
        const sites = await this.orm.call(
            "business.center.floor", "bc_get_picker_sites", [config.linkKey, resIds]);
        if (!sites.length) {
            this.notification.add(
                _t("None of the available units are drawn on a floor layout yet. Use the dropdown instead."),
                { type: "warning" });
            return;
        }
        this.dialog.add(FloorPickerDialog, {
            title: config.title,
            sites,
            siteId: (sites.find((s) => s.plans.some((p) => p.pickable)) || sites[0]).id,
            allowed: { [config.linkKey]: resIds },
            chosen: {
                bc_office: record.data.contract_space_ids.currentIds,
                bc_desk: record.data.contract_desk_ids.currentIds,
            },
            onPick: (pick) => record.update({
                [config.field]: { id: pick.res_id, display_name: pick.name },
            }),
        });
    }
}

registry.category("view_widgets").add("bc_floor_picker", {
    component: BcFloorPickerButton,
});
