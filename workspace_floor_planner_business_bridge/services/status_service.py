# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models

from odoo.addons.workspace_floor_planner.tools.constants import SUMMARY_STATUS_CODES, STATUS_UNKNOWN

# Provider key of each kind of rentable unit counted in a floor's totals.
UNIT_PROVIDER_KEYS = ("bc_office", "bc_desk", "bc_meeting_room")


class WorkspaceFloorStatusService(models.AbstractModel):
    """Count every unit of a Business Center floor in the layout totals,
    including units that are not placed on the drawing yet."""

    _inherit = "workspace.floor.status.service"

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _plan_summary(self, plan, units, unit_results, at=None):
        """Return the totals of a layout drawn for a Business Center floor.

        The totals come from the floor's own offices, desks and meeting
        rooms rather than from the shapes, so a unit counts even before it
        is drawn; ``unplaced`` tells how many are not on the drawing yet.
        Layouts not tied to a floor keep the core behaviour.
        """

        if not plan.bc_floor_id:
            return super()._plan_summary(plan, units, unit_results, at)

        providers = self.env["workspace.floor.link.registry"]._get_providers()
        floor_units = self.env["workspace.floor.bc.units"]._floor_units(plan.bc_floor_id)
        placed = set(units.filtered("link_key").mapped(lambda o: (o.link_key, o.link_res_id)))
        summary = dict.fromkeys(SUMMARY_STATUS_CODES, 0)
        unplaced = 0
        for key, records in zip(UNIT_PROVIDER_KEYS, floor_units):
            provider = providers.get(key)
            if provider is None:
                continue
            # Same access and company filtering as everywhere else.
            records = provider._fp_resolve(plan, records.ids)
            for status in provider._fp_get_statuses(records, at).values():
                summary[status if status in summary else STATUS_UNKNOWN] += 1
            unplaced += sum(1 for rec in records if (key, rec.id) not in placed)
        summary["total"] = sum(summary.values())
        summary["unplaced"] = unplaced
        return summary