# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from .portal import BusinessCenterPortal

TEAM_URL = '/my/team'


class BusinessCenterTeamPortal(BusinessCenterPortal):
    """My Team: a Tenant Corporate Admin sees and manages their company's
    members. Records are read with sudo() inside their own company only; the
    rules (add, approval, invite, remove) are res.partner's."""

    # ------------------------------------------------------------------------------
    #   MARK: HOME COUNTER
    # ------------------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'team_count' in counters:
            values['team_count'] = len(self._bc_team_members()) if self._bc_is_tenant_admin() else 0
        return values

    # ------------------------------------------------------------------------------
    #   MARK: SCOPE HELPERS
    # ------------------------------------------------------------------------------
    def _bc_team_access_denied(self):
        """My Team is for the Tenant Corporate Admin only."""

        user = request.env.user
        if user.share and not self._bc_is_tenant_admin():
            return request.redirect('/my')
        return False

    @staticmethod
    def _bc_team_members():
        """The people of the member's own company."""

        company = request.env.user.partner_id.commercial_partner_id.sudo()
        return company.child_ids.filtered(
            lambda p: not p.is_company and p.type == 'contact').sorted('name')

    def _bc_team_member(self, partner_id):
        """One person of the member's own company, or an empty recordset."""

        return self._bc_team_members().filtered(lambda p: p.id == self._bc_to_int(partner_id))[:1]

    def _bc_team_action(self, operation, done):
        """Run ``operation`` and come back to My Team with ``done`` shown, or
        roll back and show the error."""

        try:
            operation()
            request.env.flush_all()
        except (UserError, ValidationError) as exc:
            request.env.cr.rollback()
            return self._bc_redirect_with_error(TEAM_URL, exc.args[0])
        return request.redirect('%s?done=%s' % (TEAM_URL, done))

    # ------------------------------------------------------------------------------
    #   MARK: PAGES
    # ------------------------------------------------------------------------------
    @http.route([TEAM_URL], type='http', auth='user', website=True)
    def portal_my_team(self, error=None, done=None, **kw):
        """The team list and the Add member form."""

        denied = self._bc_team_access_denied()
        if denied:
            return denied
        contracts = self._bc_member_contracts()
        me = request.env.user.partner_id
        rows = [{
            'partner': member,
            'status': member._bc_team_status(),
            'contracts': contracts.filtered(lambda c, m=member: m in c.contact_ids),
            'is_me': member == me,
        } for member in self._bc_team_members()]
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'team',
            'rows': rows,
            'contracts': contracts,
            'roles': request.env['res.partner']._fields['bc_role'].selection,
            'approval': (contracts[:1].company_id or request.env.company).sudo().bc_team_approval,
            'error': error or '',
            'done': done or '',
        })
        return request.render('business_center_portal.portal_my_team', values)

    @http.route([TEAM_URL + '/add'], type='http', auth='user', website=True, methods=['POST'])
    def portal_team_add(self, **post):
        """Add a member to one of the company's running contracts."""

        denied = self._bc_team_access_denied()
        if denied:
            return denied
        contract = self._bc_member_contracts().filtered(
            lambda c: c.id == self._bc_to_int(post.get('contract_id')))[:1]
        if not contract:
            return self._bc_redirect_with_error(TEAM_URL, _("Pick one of your running contracts."))
        result = {}

        def operation():
            result['done'] = request.env['res.partner'].sudo()._bc_add_team_member(
                contract, post.get('name'), post.get('email'), post.get('role') or 'employee')

        response = self._bc_team_action(operation, 'added')
        if result.get('done') == 'pending':
            return request.redirect('%s?done=pending' % TEAM_URL)
        return response

    @http.route([TEAM_URL + '/<int:partner_id>/invite'], type='http', auth='user',
                website=True, methods=['POST'])
    def portal_team_invite(self, partner_id, **post):
        """Send the invitation again to a member who has not signed in yet."""

        denied = self._bc_team_access_denied()
        if denied:
            return denied
        member = self._bc_team_member(partner_id)
        if not member or member._bc_team_status() != 'invited':
            return self._bc_redirect_with_error(TEAM_URL, _("Only a member who has not signed in yet can be invited again."))
        return self._bc_team_action(member._bc_resend_invitation, 'invited')

    @http.route([TEAM_URL + '/<int:partner_id>/remove'], type='http', auth='user',
                website=True, methods=['POST'])
    def portal_team_remove(self, partner_id, **post):
        """Take a member who left off the contracts and revoke their login."""

        denied = self._bc_team_access_denied()
        if denied:
            return denied
        member = self._bc_team_member(partner_id)
        if not member:
            return self._bc_redirect_with_error(TEAM_URL, _("That person is not part of your team."))
        if member == request.env.user.partner_id:
            return self._bc_redirect_with_error(TEAM_URL, _("You cannot remove yourself."))
        return self._bc_team_action(member._bc_remove_from_team, 'removed')