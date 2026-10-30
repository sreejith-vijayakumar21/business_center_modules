from odoo import api, models


class WorkspaceFloorStatusService(models.AbstractModel):
    """For a layout drawn for a Business Center floor, the totals count
    every unit of the floor, including units not placed on the drawing."""

    _inherit = "workspace.floor.status.service"

    @api.model
    def _plan_summary(self, plan, units, unit_results, at=None):
        if not plan.bc_floor_id:
            return super()._plan_summary(plan, units, unit_results, at)
        registry = self.env["workspace.floor.link.registry"]
        providers = registry._get_providers()
        offices, desks, rooms = self.env["workspace.floor.bc.units"]._floor_units(plan.bc_floor_id)
        summary = dict.fromkeys(("available", "occupied", "reserved", "maintenance", "unknown"), 0)
        placed = set(units.filtered("link_key").mapped(lambda o: (o.link_key, o.link_res_id)))
        unplaced = 0
        for key, records in (("bc_office", offices), ("bc_desk", desks), ("bc_meeting_room", rooms)):
            provider = providers.get(key)
            if provider is None:
                continue
            # Same access/company filtering as everywhere else.
            records = provider._fp_resolve(plan, records.ids)
            for status in provider._fp_get_statuses(records, at).values():
                summary[status if status in summary else "unknown"] += 1
            unplaced += sum(1 for rec in records if (key, rec.id) not in placed)
        summary["total"] = sum(summary.values())
        summary["unplaced"] = unplaced
        return summary
