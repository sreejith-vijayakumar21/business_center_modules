# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Link providers mapping floor objects to Business Center records.

| Floor object             | Business Center model                         | Status from                      |
|--------------------------|-----------------------------------------------|----------------------------------|
| private_office           | business.center.space (office, not coworking) | space.state                      |
| hot_desk, dedicated_desk | business.center.desk                          | desk.state                       |
| meeting_room             | business.center.space (meeting_room)          | space.state + confirmed bookings |
| coworking_zone           | business.center.space (coworking)             | summarised from its desks        |
"""

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.workspace_floor_planner.tools.geometry import center_of, point_in_rotated_rect

# Business Center state -> floor planner status. Draft units are not ready to
# rent yet, so they show as unknown.
# Business Center state -> floor planner status.
STATE_MAP = {
    "available": "available",
    "occupied": "occupied",
    "maintenance": "maintenance",
    "draft": "draft",
}

OFFICE_DOMAIN = [("space_type", "=", "office"), ("is_coworking", "=", False)]
MEETING_ROOM_DOMAIN = [("space_type", "=", "meeting_room")]
COWORKING_DOMAIN = [("is_coworking", "=", True)]


class BusinessCenterUnits(models.AbstractModel):
    """Single place that knows which records are the rentable units of a floor."""

    _name = "workspace.floor.bc.units"
    _description = "Business Center units of a floor"

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _floor_units(self, floor):
        """Return (private offices, desks, meeting rooms) of ``floor``."""

        spaces = floor.space_ids
        offices = spaces.filtered_domain(OFFICE_DOMAIN)
        rooms = spaces.filtered_domain(MEETING_ROOM_DOMAIN)
        desks = spaces.filtered("is_coworking").desk_ids
        return offices, desks, rooms


class BusinessCenterProviderMixin(models.AbstractModel):
    """Shared behaviour of the Business Center providers."""

    _name = "workspace.floor.link.provider.bc_mixin"
    _inherit = "workspace.floor.link.provider"
    _description = "Floor link: Business Center (shared)"

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_search_domain(self, plan):
        """Only offer units of the floor this layout draws."""

        if plan.bc_floor_id:
            return [("floor_id", "=", plan.bc_floor_id.id)]
        return []

    @api.model
    def _fp_get_statuses(self, records, at=None):
        """Map each record's Business Center state to a floor planner status."""

        return {rec.id: STATE_MAP.get(rec.state, "unknown") for rec in records}

    @api.model
    def _fp_can_create(self):
        """Business Center records can be created from their shape."""

        return True

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_floor_defaults(self, plan):
        """Return form defaults placing a new record on the building and
        floor this layout draws, with the location locked in the form."""

        floor = plan.bc_floor_id
        if not floor:
            return {}
        return {
            "default_center_id": floor.center_id.id,
            "default_floor_id": floor.id,
            "bc_from_floor_layout": True,
        }


class BusinessCenterOfficeProvider(models.AbstractModel):
    """Private offices: office spaces that are not coworking."""

    _name = "workspace.floor.link.provider.bc_office"
    _inherit = "workspace.floor.link.provider.bc_mixin"
    _description = "Floor link: Business Center private offices"

    _fp_link_key = "bc_office"
    _fp_link_label = "Private Office"
    _fp_target_model = "business.center.space"
    _fp_object_types = frozenset({"private_office"})

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_target_domain(self):
        """Accept only private offices."""

        return OFFICE_DOMAIN

    @api.model
    def _fp_get_create_context(self, plan, obj):
        """Create a private office on this floor."""

        return {**self._fp_floor_defaults(plan),
                "default_space_type": "office", "default_is_coworking": False}


class BusinessCenterDeskProvider(models.AbstractModel):
    """Desks of coworking spaces."""

    _name = "workspace.floor.link.provider.bc_desk"
    _inherit = "workspace.floor.link.provider.bc_mixin"
    _description = "Floor link: Business Center desks"

    _fp_link_key = "bc_desk"
    _fp_link_label = "Desk"
    _fp_target_model = "business.center.desk"
    _fp_object_types = frozenset({"hot_desk", "dedicated_desk"})

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_get_create_context(self, plan, obj):
        """Put the new desk in the coworking space whose zone it is drawn in;
        the topmost linked zone wins when zones overlap.

        A desk always belongs to a coworking space, so creating one is
        refused until the desk sits inside a zone linked to its space.
        """

        point = center_of(obj._read_geometry())
        zones = plan.object_ids.filtered(lambda o: o.link_key == "bc_coworking" and o.link_res_id)
        for zone in zones.sorted("z_index", reverse=True):
            if point_in_rotated_rect(point, zone._read_geometry()):
                return {"default_space_id": zone.link_res_id}
        raise UserError(self.env._(
            "“%s” is not inside a coworking zone with a coworking space yet. "
            "A desk always belongs to a coworking space: select its coworking "
            "zone, create (or link) the coworking space, then create the desk.",
            obj.display_name,
        ))


class BusinessCenterCoworkingProvider(models.AbstractModel):
    """Coworking zones draw coworking spaces; their desks are linked separately."""

    _name = "workspace.floor.link.provider.bc_coworking"
    _inherit = "workspace.floor.link.provider.bc_mixin"
    _description = "Floor link: Business Center coworking spaces"

    _fp_link_key = "bc_coworking"
    _fp_link_label = "Coworking Space"
    _fp_target_model = "business.center.space"
    _fp_object_types = frozenset({"coworking_zone"})

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_target_domain(self):
        """Accept only coworking spaces."""

        return COWORKING_DOMAIN

    @api.model
    def _fp_get_create_context(self, plan, obj):
        """Create a coworking space on this floor."""

        return {**self._fp_floor_defaults(plan),
                "default_space_type": "office", "default_is_coworking": True}


class BusinessCenterMeetingRoomProvider(models.AbstractModel):
    """Meeting rooms, coloured by their state and confirmed bookings."""

    _name = "workspace.floor.link.provider.bc_meeting_room"
    _inherit = "workspace.floor.link.provider.bc_mixin"
    _description = "Floor link: Business Center meeting rooms"

    _fp_link_key = "bc_meeting_room"
    _fp_link_label = "Meeting Room"
    _fp_target_model = "business.center.space"
    _fp_object_types = frozenset({"meeting_room"})

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_target_domain(self):
        """Accept only meeting rooms."""

        return MEETING_ROOM_DOMAIN

    @api.model
    def _fp_get_create_context(self, plan, obj):
        """Create a meeting room on this floor."""

        return {**self._fp_floor_defaults(plan), "default_space_type": "meeting_room"}

    @api.model
    def _fp_is_time_dependent(self):
        """Room statuses depend on bookings, so on the selected moment."""

        return True

    @api.model
    def _fp_get_statuses(self, records, at=None):
        """Maintenance and draft come from the room; otherwise a confirmed
        booking running at that moment makes it occupied, and one later the
        same day makes it reserved."""

        statuses = super()._fp_get_statuses(records, at)
        bookable = records.filtered(lambda r: r.state in ("available", "occupied"))
        if not bookable:
            return statuses
        day, hour = self._local_moment(at)
        bookings = self.env["business.center.booking"].search([
            ("meeting_room_id", "in", bookable.ids),
            ("state", "=", "confirmed"),
            ("booking_date", "=", day),
            ("end_time", ">", hour),
        ])
        for room in bookable:
            room_bookings = bookings.filtered(lambda b: b.meeting_room_id == room)
            if room_bookings.filtered(lambda b: b.start_time <= hour):
                statuses[room.id] = "occupied"
            elif room_bookings:
                statuses[room.id] = "reserved"
            else:
                statuses[room.id] = "available"
        return statuses

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _local_moment(self, at):
        """Convert ``at`` (naive UTC, or None for now) to the user's local
        date and float hour, the way bookings store their times."""

        tz = pytz.timezone(self.env.user.tz or "UTC")
        local = pytz.utc.localize(at or fields.Datetime.now()).astimezone(tz)
        return local.date(), local.hour + local.minute / 60.0


class WorkspaceFloorLinkRegistry(models.AbstractModel):
    """Register the Business Center providers with the floor planner."""

    _inherit = "workspace.floor.link.registry"

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _get_provider_models(self):
        """Add the offices, desks, meeting rooms and coworking providers."""

        return super()._get_provider_models() + [
            "workspace.floor.link.provider.bc_office",
            "workspace.floor.link.provider.bc_desk",
            "workspace.floor.link.provider.bc_meeting_room",
            "workspace.floor.link.provider.bc_coworking",
        ]
