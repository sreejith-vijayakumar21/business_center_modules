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
    #   MARK: MEMBERSHIP HELPERS
    # ------------------------------------------------------------------------------
    def _prepare_portal_layout_values(self):
        """Add the member's membership card values; /my and /my/account
        show the card."""

        values = super()._prepare_portal_layout_values()
        values['bc_membership'] = self._bc_membership_values()
        return values

    def _bc_membership_values(self):
        """What the membership card shows the signed-in member, or {} when
        they have none (or are staff browsing the portal).

        The status is the company's. Centres are the ones this member can
        use: every running contract's for a tenant admin, only those they
        are named on for an employee, so an employee is never pointed at a
        centre they cannot book. Contract numbers are for tenant admins."""

        user = request.env.user
        if not user.share:
            return {}
        partner = user.partner_id.sudo()
        state = partner.bc_membership_state
        if state == 'none':
            return {}
        is_admin = self._bc_is_tenant_admin()
        usable = self._bc_member_contracts()
        running = state in ('active', 'expiring')
        valid_until = partner.bc_membership_valid_until
        labels = dict(partner._fields['bc_membership_state']._description_selection(request.env))
        return {
            'state': state,
            'label': labels.get(state, state),
            'company': partner.commercial_partner_id,
            'member_since': partner.bc_member_since,
            'starts_on': partner.bc_membership_starts_on,
            'valid_until': valid_until,
            'days_left': (valid_until - self._bc_today()).days
                         if state == 'expiring' and valid_until else 0,
            'centers': usable.center_id if running else partner.bc_membership_center_ids,
            'is_admin': is_admin,
            'named': is_admin or not running or bool(usable),
            'contracts': usable if is_admin else usable.browse(),
        }