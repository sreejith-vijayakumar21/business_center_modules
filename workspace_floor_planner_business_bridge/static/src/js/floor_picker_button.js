import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { FloorPickerDialog } from "@workspace_floor_planner/floor_planner/picker/floor_picker_dialog";

/**
 * "Pick from floor plan" button.
 *
 * Shows the records that may be picked on their floor layouts and fills
 * the form with the one picked. Configured by the view, so any form can
 * use it:
 *   targets        {link_key: {field, options_field, values}}: per kind of
 *                  record, the many2one to fill, the x2many listing what
 *                  may be picked, and other values to set with it
 *   title          dialog title
 *   chosen_fields  {link_key: x2many} of records already chosen elsewhere
 */
export class BcFloorPickerButton extends Component {
    static template = "workspace_floor_planner_business_bridge.FloorPickerButton";
    static props = {
        ...standardWidgetProps,
        targets: Object,
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

    /** Records that may be picked, per link key. */
    get allowed() {
        const data = this.props.record.data;
        return Object.fromEntries(
            Object.entries(this.props.targets).map(
                ([linkKey, target]) => [linkKey, data[target.options_field]?.currentIds || []]
            )
        );
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

    /** Sites and floors holding any pickable record, merged across link keys. */
    async loadSites(allowed) {
        const sites = new Map();
        for (const [linkKey, resIds] of Object.entries(allowed)) {
            if (!resIds.length) {
                continue;
            }
            const found = await this.orm.call(
                "business.center.floor", "bc_get_picker_sites", [linkKey, resIds]);
            for (const site of found) {
                const known = sites.get(site.id);
                if (!known) {
                    sites.set(site.id, { ...site, plans: site.plans.map((p) => ({ ...p })) });
                    continue;
                }
                for (const plan of site.plans) {
                    const same = known.plans.find((p) => p.id === plan.id);
                    if (same) {
                        same.pickable += plan.pickable;
                    } else {
                        known.plans.push({ ...plan });
                    }
                }
            }
        }
        return [...sites.values()];
    }

    async open() {
        const allowed = this.allowed;
        if (!Object.values(allowed).some((ids) => ids.length)) {
            this.notification.add(_t("Nothing is available to pick right now."), { type: "warning" });
            return;
        }
        const sites = await this.loadSites(allowed);
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
            allowed,
            chosen: this.chosen,
            onPick: (pick) => this.applyPick(pick),
        });
    }

    /** Set the picked target's values first (e.g. the lease type, whose
     * onchange clears the other kind), then the picked record. */
    async applyPick(pick) {
        const target = this.props.targets[pick.link_key];
        if (!target) {
            return;
        }
        const record = this.props.record;
        if (target.values) {
            await record.update(target.values);
        }
        await record.update({ [target.field]: { id: pick.res_id, display_name: pick.name } });
    }
}

registry.category("view_widgets").add("bc_floor_picker", {
    component: BcFloorPickerButton,
    extractProps: ({ options }) => ({
        targets: options.targets,
        title: options.title,
        chosenFields: options.chosen_fields,
    }),
});