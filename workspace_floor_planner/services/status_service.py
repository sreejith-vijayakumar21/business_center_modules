# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.workspace_floor_planner.tools.constants import (
    CATEGORY_RENTABLE,
    STATUS_AVAILABLE,
    STATUS_PARTIAL,
    STATUS_UNKNOWN,
    UNIT_STATUS_CODES,
    ZONE_TYPES,
)
from odoo.addons.workspace_floor_planner.tools.geometry import (
    center_of,
    point_in_rotated_rect,
)


class WorkspaceFloorStatusService(models.AbstractModel):
    """Computes the status shown on each object.

    Statuses are never stored and never accepted from the browser: every call
    asks the providers (i.e. the business system) again, batched per provider.
    """

    _name = "workspace.floor.status.service"
    _description = "Floor Plan Status Service"

    @api.model
    def _parse_at(self, at):
        if not at:
            return None
        if isinstance(at, datetime):
            return at
        try:
            return fields.Datetime.to_datetime(at)
        except (TypeError, ValueError):
            raise ValidationError(self.env._("Invalid date/time for the status view."))

    @api.model
    def _compute(self, plan, at=None):
        at = self._parse_at(at)
        registry = self.env["workspace.floor.link.registry"]
        providers = registry._get_providers()
        objects = plan.object_ids
        unit_status = {}

        for link_key, group in registry._group_by_provider(objects).items():
            provider = providers.get(link_key)
            if provider is None:  # providers are (falsy) empty recordsets
                continue
            records = provider._fp_resolve(plan, group.mapped("link_res_id"))
            raw = provider._fp_get_statuses(records, at) if records else {}
            for obj in group:
                status = raw.get(obj.link_res_id, STATUS_UNKNOWN)
                # A provider bug must not paint a wrong colour.
                unit_status[obj.id] = status if status in UNIT_STATUS_CODES else STATUS_UNKNOWN

        result = {}
        units = objects.filtered(lambda o: o.category == CATEGORY_RENTABLE)
        for obj in units:
            result[obj.id] = {"status": unit_status.get(obj.id, STATUS_UNKNOWN)}
        for zone in objects.filtered(lambda o: o.object_type in ZONE_TYPES):
            result[zone.id] = self._summarize_zone(zone, units, result)

        return {
            "summary": self._plan_summary(plan, units, result, at),
            "at": fields.Datetime.to_string(at) if at else False,
            "time_dependent": any(p._fp_is_time_dependent() for p in providers.values()),
            "computed_at": fields.Datetime.to_string(fields.Datetime.now()),
            # String keys keep the result valid for JSON and XML-RPC clients.
            "objects": {str(obj_id): info for obj_id, info in result.items()},
        }

    @api.model
    def _plan_summary(self, plan, units, unit_results, at=None):
        """Totals shown above the layout: ``{"total": n, <status>: n, ...}``.

        The core counts the rentable objects drawn on the plan. A bridge can
        override this to count the real units of the floor instead (for
        example to include units not placed on the drawing yet).
        """
        summary = dict.fromkeys(UNIT_STATUS_CODES, 0)
        for unit in units:
            summary[unit_results[unit.id]["status"]] += 1
        summary["total"] = len(units)
        return summary

    @api.model
    def _summarize_zone(self, zone, units, unit_results):
        """A zone groups the units whose centre lies inside it.

        It never claims "available" unless all its units are; mixed content
        becomes "partial" with an "x of y available" summary, while each
        desk keeps its own status.
        """
        zone_rect = zone._read_geometry()
        inside = [
            unit for unit in units
            if point_in_rotated_rect(center_of(unit._read_geometry()), zone_rect)
        ]
        statuses = [unit_results[unit.id]["status"] for unit in inside]
        total = len(statuses)
        available = statuses.count(STATUS_AVAILABLE)
        if not total or all(s == STATUS_UNKNOWN for s in statuses):
            status = STATUS_UNKNOWN
        elif len(set(statuses)) == 1:
            status = statuses[0]
        else:
            status = STATUS_PARTIAL
        return {"status": status, "available": available, "total": total}
