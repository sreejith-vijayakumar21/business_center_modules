# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models

from odoo.addons.workspace_floor_planner.tools.constants import SUMMARY_STATUS_CODES, STATUS_UNKNOWN


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

        Each provider says which records of the floor are its units, and
        only those drawn on this layout are counted; undrawn ones are
        reported as ``unplaced``. Layouts not tied to a floor keep the core
        behaviour.
        """

        if not plan.bc_floor_id:
            return super()._plan_summary(plan, units, unit_results, at)

        placed = set(units.filtered("link_key").mapped(lambda o: (o.link_key, o.link_res_id)))
        summary = dict.fromkeys(SUMMARY_STATUS_CODES, 0)
        unplaced = 0
        for key, provider in self.env["workspace.floor.link.registry"]._get_providers().items():
            if not hasattr(provider, "_bc_floor_records"):
                continue
            records = provider._fp_resolve(plan, provider._bc_floor_records(plan.bc_floor_id).ids)
            drawn = records.filtered(lambda rec: (key, rec.id) in placed)
            for status in provider._fp_get_statuses(drawn, at).values():
                summary[status if status in summary else STATUS_UNKNOWN] += 1
            unplaced += len(records - drawn)
        summary["total"] = sum(summary.values())
        summary["unplaced"] = unplaced
        return summary