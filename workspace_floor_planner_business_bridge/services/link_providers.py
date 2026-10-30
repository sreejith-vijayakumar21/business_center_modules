"""Link providers mapping floor objects to Business Center records.

Mapping (see README):

| Floor object            | Business Center model                         | Status from                     |
|-------------------------|-----------------------------------------------|---------------------------------|
| private_office          | business.center.space (office, not coworking) | space.state                     |
| hot_desk/dedicated_desk | business.center.desk                          | desk.state                      |
| meeting_room            | business.center.space (meeting_room)          | space.state + confirmed bookings|
"""


import pytz

from odoo import api, fields, models

# Business Center state -> floor planner status. "draft" units are not
# ready to rent yet, so they show as unknown.
STATE_MAP = {
    "available": "available",
    "occupied": "occupied",
    "maintenance": "maintenance",
    "draft": "unknown",
}

OFFICE_DOMAIN = [("space_type", "=", "office"), ("is_coworking", "=", False)]
MEETING_ROOM_DOMAIN = [("space_type", "=", "meeting_room")]


class BusinessCenterUnits(models.AbstractModel):
    """Single place that knows which records are the rentable units of a floor."""

    _name = "workspace.floor.bc.units"
    _description = "Business Center units of a floor"

    @api.model
    def _floor_units(self, floor):
        """Return (private offices, desks, meeting rooms) of ``floor``."""
        spaces = floor.space_ids
        offices = spaces.filtered_domain(OFFICE_DOMAIN)
        rooms = spaces.filtered_domain(MEETING_ROOM_DOMAIN)
        desks = spaces.filtered("is_coworking").desk_ids
        return offices, desks, rooms


class BusinessCenterProviderMixin(models.AbstractModel):
    """Shared behaviour of the three Business Center providers."""

    _name = "workspace.floor.link.provider.bc_mixin"
    _inherit = "workspace.floor.link.provider"
    _description = "Floor link: Business Center (shared)"

    @api.model
    def _fp_search_domain(self, plan):
        # Only offer units of the floor this layout draws.
        if plan.bc_floor_id:
            return [("floor_id", "=", plan.bc_floor_id.id)]
        return []

    @api.model
    def _fp_get_statuses(self, records, at=None):
        return {rec.id: STATE_MAP.get(rec.state, "unknown") for rec in records}


class BusinessCenterOfficeProvider(models.AbstractModel):
    _name = "workspace.floor.link.provider.bc_office"
    _inherit = "workspace.floor.link.provider.bc_mixin"
    _description = "Floor link: Business Center private offices"

    _fp_link_key = "bc_office"
    _fp_link_label = "Private Office"
    _fp_target_model = "business.center.space"
    _fp_object_types = frozenset({"private_office"})

    @api.model
    def _fp_target_domain(self):
        return OFFICE_DOMAIN


class BusinessCenterDeskProvider(models.AbstractModel):
    _name = "workspace.floor.link.provider.bc_desk"
    _inherit = "workspace.floor.link.provider.bc_mixin"
    _description = "Floor link: Business Center desks"

    _fp_link_key = "bc_desk"
    _fp_link_label = "Desk"
    _fp_target_model = "business.center.desk"
    _fp_object_types = frozenset({"hot_desk", "dedicated_desk"})


class BusinessCenterMeetingRoomProvider(models.AbstractModel):
    _name = "workspace.floor.link.provider.bc_meeting_room"
    _inherit = "workspace.floor.link.provider.bc_mixin"
    _description = "Floor link: Business Center meeting rooms"

    _fp_link_key = "bc_meeting_room"
    _fp_link_label = "Meeting Room"
    _fp_target_model = "business.center.space"
    _fp_object_types = frozenset({"meeting_room"})

    @api.model
    def _fp_target_domain(self):
        return MEETING_ROOM_DOMAIN

    @api.model
    def _fp_is_time_dependent(self):
        return True

    @api.model
    def _local_moment(self, at):
        """Bookings store a local date and float hours: convert ``at``
        (naive UTC, or None for now) to the user's local date and hour."""
        tz = pytz.timezone(self.env.user.tz or "UTC")
        local = pytz.utc.localize(at or fields.Datetime.now()).astimezone(tz)
        return local.date(), local.hour + local.minute / 60.0

    @api.model
    def _fp_get_statuses(self, records, at=None):
        """Maintenance/draft come from the room; otherwise a confirmed
        booking running at that moment makes it occupied, one later the
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


class WorkspaceFloorLinkRegistry(models.AbstractModel):
    _inherit = "workspace.floor.link.registry"

    @api.model
    def _get_provider_models(self):
        return super()._get_provider_models() + [
            "workspace.floor.link.provider.bc_office",
            "workspace.floor.link.provider.bc_desk",
            "workspace.floor.link.provider.bc_meeting_room",
        ]
