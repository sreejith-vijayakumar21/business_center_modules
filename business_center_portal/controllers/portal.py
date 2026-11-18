# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, fields
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal

TENANT_ADMIN_GROUP = 'business_center_portal.group_bc_tenant_admin'
TENANT_EMPLOYEE_GROUP = 'business_center_portal.group_bc_tenant_employee'


class BusinessCenterPortal(CustomerPortal):
    """Shared settings and helpers for every portal page added by this module.

    Anything that both contracts and bookings need lives here, so it is
    written once instead of being repeated in each controller file.
    """

    # How many rows each portal list page shows before paging.
    _items_per_page = 8

    # ------------------------------------------------------------------------------
    #   MARK: ACCESS HELPERS
    # ------------------------------------------------------------------------------
    def _bc_is_tenant_admin(self):
        return request.env.user.has_group(TENANT_ADMIN_GROUP)

    def _bc_booking_access_denied(self):
        """Booking pages are for Business Center tenants only.

        ``user.share`` is True for portal logins only, so an internal user
        browsing the portal is never blocked by this.
        """
        user = request.env.user
        if user.share and not user.has_group(TENANT_EMPLOYEE_GROUP):
            return request.redirect('/my')
        return False
    
    def _bc_member_contracts(self, extra_domain=None):
        """Running contracts this member may act on: any of the company's
        for a corporate admin, the ones they are named on for an employee.
        ``extra_domain`` narrows it for one feature."""

        user = request.env.user
        domain = [
            ('partner_id', 'child_of', user.partner_id.commercial_partner_id.id),
            ('state', '=', 'active'),
        ]
        if not self._bc_is_tenant_admin():
            domain.append(('contact_ids', 'in', [user.partner_id.id]))
        return request.env['business.center.contract'].sudo().search(domain + (extra_domain or []))

    # ------------------------------------------------------------------------------
    #   MARK: FORM VALUE HELPERS
    # ------------------------------------------------------------------------------
    @staticmethod
    def _bc_today():
        """Today's date at the business centre, not the server's UTC date."""

        return request.env['business.center.booking'].sudo()._local_now().date()

    @staticmethod
    def _bc_to_int(value):
        """An id from the form or URL, or 0 if it was tampered with."""

        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _bc_parse_date(value):
        """A date from the form, or False when missing or malformed."""

        try:
            return fields.Date.to_date(value) if value else False
        except ValueError:
            return False

    @staticmethod
    def _hhmm_to_float(value, label):
        """Turn '09:30' from the form into the 9.5 float the models store."""

        try:
            hours, minutes = value.split(':')
            result = int(hours) + int(minutes) / 60.0
        except (AttributeError, ValueError):
            raise UserError(_("Please pick a valid %s.") % label)
        if not 0.0 <= result <= 24.0:
            raise UserError(_("Please pick a valid %s.") % label)
        return result

    def _bc_parse_time(self, value):
        """'09:30' as 9.5, or None when missing or malformed (no error)."""

        try:
            return self._hhmm_to_float(value, '') if value else None
        except UserError:
            return None

    @staticmethod
    def _bc_float_to_hhmm(value):
        """9.5 as '09:30' for a time input, or '' for None."""

        if value is None:
            return ''
        total = round(value * 60)
        return '%02d:%02d' % (total // 60, total % 60)
    
    # ------------------------------------------------------------------------------
    #   MARK: FLOOR PICKER HELPERS
    # ------------------------------------------------------------------------------
    # Shared by every portal floor picker (hot desks, meeting rooms, ...). All
    # reads are sudo(); callers pass only records already inside the member's
    # own scope, and every route checks the floor belongs to that scope.

    @staticmethod
    def _bc_floor_sites(link_key, center, records, free_records):
        """Floors of ``center`` that draw ``records``, each counting the
        ``free_records`` drawn on it. A floor stays listed when nothing on it
        is free, so the member sees its units in red instead of the floor
        vanishing."""

        if not (center and records):
            return []
        Floor = request.env['business.center.floor'].sudo()
        sites = Floor.bc_get_picker_sites(link_key, records.ids)
        free_sites = Floor.bc_get_picker_sites(link_key, free_records.ids) if free_records else []
        free_by_plan = {plan['id']: plan['pickable'] for site in free_sites for plan in site['plans']}
        # The note counts free units missing from every layout: take it from the free call.
        free_notes = {site['id']: site['note'] for site in free_sites}
        for site in sites:
            site['note'] = free_notes.get(site['id'], False)
            for plan in site['plans']:
                plan['pickable'] = free_by_plan.get(plan['id'], 0)
        return sites

    @staticmethod
    def _bc_floor_plan(plan_id, center):
        """The floor plan when it belongs to ``center``, else an empty recordset."""

        plan = request.env['workspace.floor.plan'].sudo().browse(plan_id).exists()
        if center and plan and plan.bc_floor_id.center_id == center:
            return plan
        return plan.browse()

    @staticmethod
    def _bc_floor_layout(plan):
        """The drawing of ``plan`` for a read-only portal picker: no palette,
        providers or edit rights."""

        layout = request.env['workspace.floor.layout.service'].sudo()._load(plan)
        layout.update(presets=[], providers=[])
        layout['plan']['can_edit'] = False
        return layout

    @staticmethod
    def _bc_floor_slot_states(plan, link_key, state_of):
        """{shape id: state} for every shape of ``plan`` linked through
        ``link_key``. ``state_of(record_id)`` decides the state, or returns
        None for a record outside the member's scope (left uncoloured)."""

        objects = request.env['workspace.floor.plan.object'].sudo().search([
            ('plan_id', '=', plan.id),
            ('link_key', '=', link_key),
            ('link_res_id', '!=', False),
        ])
        states = {}
        for obj in objects:
            state = state_of(obj.link_res_id)
            if state:
                states[obj.id] = state
        return states

    @staticmethod
    def _bc_unit_details(link_key, record, image_url=False):
        """Side panel details of ``record`` from its link provider, with an
        image URL the portal can open."""

        provider = request.env['workspace.floor.link.registry'].sudo()._get_provider(link_key)
        details = provider._fp_get_details(record) or False
        if details:
            details['image_url'] = image_url
        return details

    @staticmethod
    def _bc_image_response(record, field_name='image_1920'):
        """A photo of ``record`` sized for the details panel."""

        return request.env['ir.binary']._get_image_stream_from(
            record, field_name, width=480, height=360).get_response()