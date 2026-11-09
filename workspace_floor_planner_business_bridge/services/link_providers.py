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
from odoo.tools import format_amount, format_date, formatLang

from odoo.addons.workspace_floor_planner.tools.geometry import center_of, point_in_rotated_rect

from odoo.addons.workspace_floor_planner_business_bridge.models.business_center_space import (
    DESK_LINK_KEYS,
    release_floor_links,
)

import logging

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
    _bc_has_details = False

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
    
    @api.model
    def _fp_check_remove(self, plan, records):
        """Only shapes of Draft units may be removed: a space or desk that is
        available, occupied or under maintenance keeps its place on the floor.
        Reset it to Draft first to redraw it."""

        in_use = records.filtered(lambda r: r.state != "draft")
        if not in_use:
            return
        unit = in_use[0]
        states = dict(unit._fields["state"]._description_selection(self.env))
        raise UserError(self.env._(
            "Only Draft spaces can be removed from or unlinked on the layout. "
            "“%(name)s” is %(state)s.",
            name=unit.display_name,
            state=states.get(unit.state, unit.state),
        ))

    @api.model
    def _fp_release(self, plan, records):
        """A Draft unit taken off its floor layout is deleted when it has no
        history, and archived when it has. Providers extend
        ``_fp_archive_released`` for what else must follow an archived unit."""

        drafts = records.filtered(lambda r: r.state == "draft")
        kept = drafts.filtered(lambda r: r._bc_has_history())
        (drafts - kept).unlink()
        if kept:
            self._fp_archive_released(kept)

    @api.model
    def _fp_archive_released(self, records):
        """Archive released units that have history."""

        records.write({"active": False})
        
    @api.model
    def _fp_get_details(self, record):
        """Describe ``record`` for the floor picker's side panel: photo,
        facts, amenities and, when occupied, the current lease. Providers
        opt in with ``_bc_has_details`` and fill in the ``_bc_detail_*``
        hooks; the layout of the panel stays the same for all of them."""

        if not self._bc_has_details:
            return False
        sections = []
        amenities = self._bc_detail_amenities(record)
        if amenities:
            sections.append({
                "title": self.env._("Amenities"),
                "tags": amenities.sorted("name").mapped("name"),
            })
        lease = self._bc_lease_section(record)
        if lease:
            sections.append(lease)
        return {
            "title": record.display_name,
            "subtitle": self._fp_link_label,
            "image_url": self._bc_image_url(self._bc_detail_photo_record(record)),
            "facts": [fact for fact in self._bc_detail_facts(record) if fact["value"]],
            "sections": sections,
        }

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
        
    @api.model
    def _bc_floor_records(self, floor):
        """This provider's rentable units on ``floor``, for the floor totals.
        Spaces by default; desk providers override it."""

        return floor.space_ids.filtered_domain(self._fp_target_domain())
    
    @api.model
    def _local_moment(self, at):
        """Convert ``at`` (naive UTC, or None for now) to the user's local
        date and float hour, the way bookings store their times."""

        tz = pytz.timezone(self.env.user.tz or "UTC")
        local = pytz.utc.localize(at or fields.Datetime.now()).astimezone(tz)
        return local.date(), local.hour + local.minute / 60.0

    @api.model
    def _bc_booking_statuses(self, records, at, booking_model, resource_field, holding_states):
        """Statuses of bookable units at ``at``: draft and maintenance come
        from the unit; otherwise a holding booking running then makes it
        occupied, one later the same day reserved, none available."""

        statuses = {rec.id: STATE_MAP.get(rec.state, "unknown") for rec in records}
        bookable = records.filtered(lambda r: r.state in ("available", "occupied"))
        if not bookable:
            return statuses
        day, hour = self._local_moment(at)
        bookings = self.env[booking_model].sudo().search([
            (resource_field, "in", bookable.ids),
            ("state", "in", holding_states),
            ("booking_date", "=", day),
            ("end_time", ">", hour),
        ])
        for rec in bookable:
            mine = bookings.filtered(lambda b: b[resource_field] == rec)
            if mine.filtered(lambda b: b.start_time <= hour):
                statuses[rec.id] = "occupied"
            elif mine:
                statuses[rec.id] = "reserved"
            else:
                statuses[rec.id] = "available"
        return statuses
    
    @api.model
    def _bc_detail_facts(self, record):
        """``[{"label", "value"}]`` describing the unit; empty values are
        dropped. Providers that show details override it."""

        return []

    @api.model
    def _bc_detail_amenities(self, record):
        """Amenities of the unit; desks override it."""

        return record.amenity_ids

    @api.model
    def _bc_detail_photo_record(self, record):
        """Record whose photo represents the unit; desks override it."""

        return record

    @api.model
    def _bc_image_url(self, record):
        """URL of ``record``'s main photo, resized for the panel, or False."""

        if not record or "image_1920" not in record._fields or not record.image_1920:
            return False
        return f"/web/image/{record._name}/{record.id}/image_1920/480x360"

    @api.model
    def _bc_amount(self, record, amount):
        """``amount`` formatted in the unit's currency, or False when zero."""

        currency = record.currency_id or self.env.company.currency_id
        return amount and format_amount(self.env, amount, currency)

    @api.model
    def _bc_rent_fact(self, record):
        return {"label": self.env._("Monthly rent"),
                "value": self._bc_amount(record, record.monthly_rent)}

    @api.model
    def _bc_hourly_rate_fact(self, record):
        return {"label": self.env._("Hourly rate"),
                "value": self._bc_amount(record, record.hourly_rate)}

    @api.model
    def _bc_seats_fact(self, seats):
        return {"label": self.env._("Capacity"),
                "value": seats and self.env._("%s seat(s)", seats)}

    @api.model
    def _bc_area_fact(self, space):
        return {"label": self.env._("Floor area"),
                "value": space.area_sqm and self.env._(
                    "%s m²", formatLang(self.env, space.area_sqm, digits=1))}

    @api.model
    def _bc_space_fact(self, desk):
        return {"label": self.env._("Coworking space"), "value": desk.space_id.display_name}

    @api.model
    def _bc_lease_section(self, record):
        """Tenant, contract and period of an occupied unit, else False."""

        if record.state != "occupied" or not record.occupant_id:
            return False
        period = " – ".join(filter(None, (
            record.contract_start_date and format_date(self.env, record.contract_start_date),
            record.contract_end_date and format_date(self.env, record.contract_end_date),
        )))
        facts = [
            {"label": self.env._("Leased to"), "value": record.occupant_id.display_name},
            {"label": self.env._("Contract"), "value": record.current_contract_id.display_name},
            {"label": self.env._("Period"), "value": period},
        ]
        return {
            "title": self.env._("Current lease"),
            "facts": [fact for fact in facts if fact["value"]],
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
    _bc_has_details = True

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
        
    @api.model
    def _bc_detail_facts(self, record):
        """Seats, floor area and monthly rent of the office."""

        return [self._bc_seats_fact(record.capacity), self._bc_area_fact(record),
                self._bc_rent_fact(record)]


class BusinessCenterDeskProvider(models.AbstractModel):
    """Dedicated desks of coworking spaces, leased on contracts."""

    _name = "workspace.floor.link.provider.bc_desk"
    _inherit = "workspace.floor.link.provider.bc_mixin"
    _description = "Floor link: Business Center dedicated desks"

    _fp_link_key = "bc_desk"
    _fp_link_label = "Desk"
    _fp_target_model = "business.center.desk"
    _fp_object_types = frozenset({"dedicated_desk"})
    # Desk type of the records this provider draws; subclasses change only this.
    _fp_desk_type = "dedicated"
    _bc_has_details = True

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_target_domain(self):
        """Accept only desks of this provider's type."""

        return [("desk_type", "=", self._fp_desk_type)]

    @api.model
    def _bc_floor_records(self, floor):
        """Desks of this type in the floor's coworking spaces."""

        return floor.space_ids.filtered("is_coworking").desk_ids.filtered_domain(self._fp_target_domain())

    @api.model
    def _fp_get_create_context(self, plan, obj):
        """Put the new desk in the coworking space it is drawn in, with this
        provider's desk type; a linked coworking area wins over an unlinked
        one, the topmost over the rest."""

        point = center_of(obj._read_geometry())
        areas = plan.object_ids.filtered(
            lambda o: o.object_type == "coworking_zone"
            and point_in_rotated_rect(point, o._read_geometry())
        ).sorted("z_index", reverse=True)
        linked = areas.filtered(lambda a: a.link_key == "bc_coworking" and a.link_res_id)[:1]
        if linked:
            return {
                "default_space_id": linked.link_res_id,
                "default_desk_type": self._fp_desk_type,
                "bc_from_floor_layout": True,
            }
        if areas:
            raise UserError(self.env._(
                "Create the coworking space first, then create the desk."))
        raise UserError(self.env._(
            "Place the desk inside a coworking space on the layout first, "
            "then create the desk."))
        
    @api.model
    def _bc_detail_facts(self, record):
        """The coworking space the desk sits in, one seat, and its rent."""

        return [self._bc_space_fact(record), self._bc_seats_fact(1), self._bc_rent_fact(record)]

    @api.model
    def _bc_detail_amenities(self, record):
        """A desk offers its coworking space's amenities, as on the lease
        agreement."""

        return record.space_id.amenity_ids

    @api.model
    def _bc_detail_photo_record(self, record):
        """A desk shows its coworking space's photo."""

        return record.space_id


class BusinessCenterHotDeskProvider(models.AbstractModel):
    """Hot desks: shared desks of coworking spaces, booked by the hour."""

    _name = "workspace.floor.link.provider.bc_hot_desk"
    _inherit = "workspace.floor.link.provider.bc_desk"
    _description = "Floor link: Business Center hot desks"

    _fp_link_key = "bc_hot_desk"
    _fp_link_label = "Hot Desk"
    _fp_object_types = frozenset({"hot_desk"})
    _fp_desk_type = "hot"
    _bc_has_details = True
    
    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_is_time_dependent(self):
        """Hot desk statuses depend on bookings, so on the selected moment."""

        return True

    @api.model
    def _fp_get_statuses(self, records, at=None):
        """Hot desk statuses from their state and bookings at ``at``."""

        return self._bc_booking_statuses(records, at, "business.center.desk.booking",
                                         "desk_id", ("confirmed", "checked_in"))
        
    @api.model
    def _bc_detail_facts(self, record):
        """The coworking space and hourly rate of the hot desk."""

        return [self._bc_space_fact(record), self._bc_hourly_rate_fact(record)]


class BusinessCenterCoworkingProvider(models.AbstractModel):
    """Coworking zones draw coworking spaces; their desks are linked separately."""

    _name = "workspace.floor.link.provider.bc_coworking"
    _inherit = "workspace.floor.link.provider.bc_mixin"
    _description = "Floor link: Business Center coworking spaces"

    _fp_link_key = "bc_coworking"
    _fp_link_label = "Coworking Space"
    _fp_target_model = "business.center.space"
    _fp_object_types = frozenset({"coworking_zone"})
    _bc_has_details = True

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
        
    @api.model
    def _fp_archive_released(self, records):
        """An archived coworking space takes its desks along, and their shapes
        are freed: desks cannot be used without their space."""

        desks = records.desk_ids
        if desks:
            release_floor_links(self.env, DESK_LINK_KEYS, desks.ids)
            desks.write({"active": False})
        super()._fp_archive_released(records)
        
    @api.model
    def _bc_floor_records(self, floor):
        """A coworking space is not counted itself; its desks are."""

        return self._fp_target().browse()
    
    @api.model
    def _bc_detail_facts(self, record):
        """Floor area of the coworking space; its desks are picked one by one."""

        return [self._bc_area_fact(record)]


class BusinessCenterMeetingRoomProvider(models.AbstractModel):
    """Meeting rooms, coloured by their state and confirmed bookings."""

    _name = "workspace.floor.link.provider.bc_meeting_room"
    _inherit = "workspace.floor.link.provider.bc_mixin"
    _description = "Floor link: Business Center meeting rooms"

    _fp_link_key = "bc_meeting_room"
    _fp_link_label = "Meeting Room"
    _fp_target_model = "business.center.space"
    _fp_object_types = frozenset({"meeting_room"})
    _bc_has_details = True

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
        """Room statuses from their state and confirmed bookings at ``at``."""

        return self._bc_booking_statuses(records, at, "business.center.booking",
                                         "meeting_room_id", ("confirmed",))
        
    @api.model
    def _bc_detail_facts(self, record):
        """Seats, hourly rate and opening hours of the meeting room."""

        return [
            self._bc_seats_fact(record.capacity),
            self._bc_hourly_rate_fact(record),
            {"label": self.env._("Opening hours"), "value": record.operating_hours_display},
        ]


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
            "workspace.floor.link.provider.bc_hot_desk",
        ]
