# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tools import email_normalize


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    bc_role = fields.Selection([
        ('employee', 'Tenant Employee'),
        ('admin', 'Tenant Corporate Admin'),
    ], string='Business Center Role',
       help="Role granted to this contact's portal login")

    bc_center_ids = fields.Many2many('business.center', string='Business Centres',
                                     compute='_compute_bc_center_ids', search='_search_bc_center_ids',
                                     help="Centres this contact's company holds an active contract in.")

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('commercial_partner_id')
    def _compute_bc_center_ids(self):
        """Centres this contact's company holds an active contract in.

        Desks are mapped through their space as well as offices: a desk-only
        tenant used to yield an empty set, and four portal record rules key off
        this field, so those tenants saw nothing in the backend at all.
        """

        Contract = self.env['business.center.contract'].sudo()
        for partner in self:
            contracts = Contract.search([
                ('partner_id', 'child_of', partner.commercial_partner_id.id),
                ('state', '=', 'active'),
            ])
            partner.bc_center_ids = (
                contracts.mapped('leased_asset_ids.space_id.center_id')
                | contracts.mapped('leased_asset_ids.desk_id.space_id.center_id')
            )

    def _search_bc_center_ids(self, operator, value):
        """Not searchable: the record rules read .ids directly, and a real
        search would mean reversing the contract lookup for every partner."""

        return [('id', '=', 0)]

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._bc_sync_role()
        return partners

    def write(self, vals):
        res = super().write(vals)
        if 'bc_role' in vals:
            self._bc_sync_role()
        return res

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _bc_sync_role(self):
        """Keep the portal user's groups in step with the role on the contact."""

        emp = self.env.ref('business_center_portal.group_bc_tenant_employee')
        adm = self.env.ref('business_center_portal.group_bc_tenant_admin')
        for partner in self:
            user = partner.user_ids[:1]
            if not user or not user.share:
                continue
            user.sudo().group_ids = [(3, emp.id), (3, adm.id)]
            if partner.bc_role == 'employee':
                user.sudo().group_ids = [(4, emp.id)]
            elif partner.bc_role == 'admin':
                user.sudo().group_ids = [(4, adm.id)]

    def _bc_grant_portal_access(self):
        """Give each of these tenant contacts a portal login and email them
        the invitation, exactly as Action > Grant portal access does; the
        Business Center role is applied by portal.wizard.user. Contacts who
        already have a login are left alone.

        :return: {partner: reason} for the contacts that could not be invited
        """

        skipped = {}
        Wizard = self.env['portal.wizard'].sudo()
        for partner in self.filtered(lambda p: not p.user_ids):
            if not partner.email:
                skipped[partner] = _("no email address")
                continue
            try:
                with self.env.cr.savepoint():
                    wizard = Wizard.create({'partner_ids': [Command.set(partner.ids)]})
                    wizard.user_ids.action_grant_access()
            except (UserError, ValidationError) as exc:
                skipped[partner] = exc.args[0]
        return skipped
    
    # ------------------------------------------------------------------------------
    #   MARK: TEAM METHODS
    # ------------------------------------------------------------------------------
    def _bc_team_status(self):
        """Where this member of a tenant's team stands: 'pending' (waiting for
        approval), 'rejected', 'active' (has signed in), 'invited' (login
        sent, never used) or 'no_access'."""

        self.ensure_one()
        last = self.env['business.center.member.request'].sudo().search(
            [('partner_id', '=', self.id)], limit=1)
        if last.state == 'pending':
            return 'pending'
        user = self.user_ids[:1]
        if not user:
            return 'rejected' if last.state == 'rejected' else 'no_access'
        return 'active' if user.login_date else 'invited'

    @api.model
    def _bc_add_team_member(self, contract, name, email, role):
        """A tenant's administrator adds someone to their team on ``contract``.
        They join it at once and are invited, or, when the centre approves new
        members first, a request waits for staff.

        :return: 'added' or 'pending'
        """

        name, email = (name or '').strip(), email_normalize(email or '')
        if not name:
            raise UserError(_("Enter the member's name."))
        if not email:
            raise UserError(_("Enter a valid email address."))
        if role not in dict(self._fields['bc_role'].selection):
            raise UserError(_("Pick a role."))
        if contract.state not in ('upcoming', 'active'):
            raise UserError(_("Pick one of your running contracts."))
        company = contract.partner_id
        taken = self.env['res.users'].sudo().with_context(active_test=False).search_count([
            ('login', '=ilike', email),
            ('partner_id.commercial_partner_id', '!=', company.id),
        ], limit=1)
        if taken:
            raise UserError(_("%s already has an account with another company. "
                              "Please contact the business centre.", email))

        partner = company.child_ids.filtered(lambda p: email_normalize(p.email or '') == email)[:1]
        if partner:
            partner.bc_role = role
        else:
            partner = self.create({'name': name, 'email': email, 'parent_id': company.id,
                                   'type': 'contact', 'bc_role': role})
        if partner in contract.contact_ids:
            raise UserError(_("%s is already on this contract.", partner.name))

        if contract.company_id.bc_team_approval:
            Request = self.env['business.center.member.request']
            if Request.search_count([('partner_id', '=', partner.id), ('contract_id', '=', contract.id),
                                     ('state', '=', 'pending')], limit=1):
                raise UserError(_("%s is already waiting for approval.", partner.name))
            Request.create({'partner_id': partner.id, 'contract_id': contract.id,
                            'role': role})._bc_request_review()
            return 'pending'

        contract.write({'contact_ids': [Command.link(partner.id)]})
        contract.message_post(body=_("%(admin)s added %(member)s to the team.",
                                     admin=self.env.user.name, member=partner.name))
        return 'added'

    def _bc_resend_invitation(self):
        """Send the portal invitation again to members who have not signed in yet."""

        wizard = self.env['portal.wizard'].sudo().create({'partner_ids': [Command.set(self.ids)]})
        wizard.user_ids.action_invite_again()

    def _bc_remove_from_team(self):
        """Someone left the tenant company: take them off its running
        contracts and revoke their portal login."""

        contracts = self.env['business.center.contract'].sudo().search([
            ('contact_ids', 'in', self.ids), ('state', 'in', ('upcoming', 'active'))])
        if contracts:
            contracts.write({'contact_ids': [Command.unlink(p.id) for p in self]})
        with_login = self.filtered('user_ids')
        if with_login:
            wizard = self.env['portal.wizard'].sudo().create(
                {'partner_ids': [Command.set(with_login.ids)]})
            wizard.user_ids.action_revoke_access()