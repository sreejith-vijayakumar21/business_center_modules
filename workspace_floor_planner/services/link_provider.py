# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models

from odoo.addons.workspace_floor_planner.tools.constants import (
    RENTABLE_TYPES,
    STATUS_UNKNOWN,
)


class WorkspaceFloorLinkProvider(models.AbstractModel):
    """Base class ("interface") for linking floor objects to business records.

    A bridge addon creates one provider per kind of business record, e.g.::

        class MeetingRoomProvider(models.AbstractModel):
            _name = "workspace.floor.link.provider.meeting_room"
            _inherit = "workspace.floor.link.provider"
            _description = "Floor link: meeting rooms"

            _fp_link_key = "meeting_room"
            _fp_link_label = "Meeting Room"
            _fp_target_model = "my_business.meeting.room"
            _fp_object_types = frozenset({"meeting_room"})

            def _fp_get_statuses(self, records, at=None):
                return {room.id: room._my_existing_status_method(at) for room in records}

    and registers it in ``workspace.floor.link.registry._get_provider_models``.

    The base class already handles the security-sensitive parts (record
    existence, read access, company boundaries, opening the record), so a
    provider normally only overrides ``_fp_get_statuses`` and, if needed,
    ``_fp_search_domain``.
    """

    _name = "workspace.floor.link.provider"
    _description = "Floor Plan Link Provider (base)"

    # Stable identifier stored on objects. Never change it once data exists.
    _fp_link_key = None
    _fp_link_label = None
    _fp_target_model = None
    # Which floor object types may be linked through this provider.
    _fp_object_types = RENTABLE_TYPES

    # ------------------------------------------------------------------------------
    #   MARK: DESCRIPTION
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_is_usable(self):
        """Return False when the target model is not installed in this database."""

        return bool(self._fp_link_key and self._fp_target_model
                    and self._fp_target_model in self.env)

    @api.model
    def _fp_describe(self):
        """Return what the editor needs to know about this provider."""

        return {
            "key": self._fp_link_key,
            "label": self._fp_link_label or self._fp_link_key,
            "object_types": sorted(self._fp_object_types),
            "can_create": self._fp_can_create(),
        }

    @api.model
    def _fp_target(self):
        """Return the (empty) recordset of the target model."""

        return self.env[self._fp_target_model]

    # ------------------------------------------------------------------------------
    #   MARK: RECORD CREATION
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_can_create(self):
        """Return True when users may create a new target record from a floor
        object. Bridges opt in; the core never assumes it can create business
        records."""

        return False

    @api.model
    def _fp_get_create_context(self, plan, obj):
        """Return form defaults (``default_*`` context keys) for a record
        created from ``obj`` on ``plan``, e.g. the building and floor it is
        drawn on."""

        return {}

    # ------------------------------------------------------------------------------
    #   MARK: LOOKUP (always as the current user, never sudo)
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_target_domain(self):
        """Return the records of the target model this provider accepts at
        all, e.g. only meeting rooms of a shared "space" model. Enforced on
        search *and* when validating a link."""

        return []

    @api.model
    def _fp_search_domain(self, plan):
        """Return an extra restriction on selectable records. Override in
        bridges, e.g. to only offer desks of the plan's building."""

        return []

    @api.model
    def _fp_company_domain(self, plan):
        """Restrict targets to the plan's company, or to the user's companies
        when the plan is shared."""

        target = self._fp_target()
        companies = plan.company_id or self.env.companies
        return target._check_company_domain(companies)

    @api.model
    def _fp_search(self, plan, query, limit):
        """Search link targets matching ``query`` within every restriction."""

        target = self._fp_target()
        domain = [
            *self._fp_target_domain(),
            *self._fp_company_domain(plan),
            *self._fp_search_domain(plan),
        ]
        if query:
            domain.append(("display_name", "ilike", query))
        records = target.search(domain, limit=limit)
        return [{"id": rec.id, "display_name": rec.display_name} for rec in records]

    @api.model
    def _fp_resolve(self, plan, res_ids):
        """Return only the records that exist, are readable by the current
        user and belong to a company compatible with the plan."""

        target = self._fp_target()
        records = target.browse(res_ids).exists()._filtered_access("read")
        if self._fp_target_domain():
            records = records.filtered_domain(self._fp_target_domain())
        if "company_id" in target._fields:
            allowed = plan.company_id or self.env.companies
            records = records.filtered(lambda r: not r.company_id or r.company_id in allowed)
        return records

    # ------------------------------------------------------------------------------
    #   MARK: STATUS AND NAVIGATION
    # ------------------------------------------------------------------------------
    @api.model
    def _fp_get_statuses(self, records, at=None):
        """Return ``{record_id: status_code}`` for already-resolved records.

        ``at`` is a naive UTC datetime or None (= now). Bridges MUST compute
        this with the business system's own availability logic. Returning
        "unknown" is always allowed. Codes come from
        ``tools.constants.UNIT_STATUS_CODES``.
        """

        return {rec.id: STATUS_UNKNOWN for rec in records}

    @api.model
    def _fp_is_time_dependent(self):
        """Return True when statuses depend on the selected date/time."""

        return False

    @api.model
    def _fp_get_open_action(self, record):
        """Return the action that opens ``record`` in its own form."""

        return {
            "type": "ir.actions.act_window",
            "res_model": record._name,
            "res_id": record.id,
            "views": [[False, "form"]],
            "target": "current",
            "name": record.display_name,
        }
