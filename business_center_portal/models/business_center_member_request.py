# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError

REVIEW_ACTIVITY = 'mail.mail_activity_data_todo'


class BusinessCenterMemberRequest(models.Model):
    """A tenant administrator's request to add a member to a contract, used
    when the company approves new team members first. Approving adds the
    member to the contract, which invites them to the portal."""

    _name = 'business.center.member.request'
    _description = 'Team Member Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    partner_id = fields.Many2one('res.partner', string='Member', required=True, ondelete='cascade')
    email = fields.Char(related='partner_id.email')
    role = fields.Selection(
        selection=lambda self: self.env['res.partner']._fields['bc_role'].selection,
        string='Role', required=True, default='employee')
    contract_id = fields.Many2one('business.center.contract', string='Contract',
                                  required=True, ondelete='cascade')
    tenant_id = fields.Many2one(related='contract_id.partner_id', string='Tenant', store=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True)
    requested_by_id = fields.Many2one('res.users', string='Requested By', required=True,
                                      default=lambda self: self.env.user)
    state = fields.Selection([
        ('pending', 'Awaiting Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Status', default='pending', required=True, tracking=True)
    reject_reason = fields.Text(string='Rejection Reason',
                                help="Sent to the tenant's administrator when you reject.")
    decided_by_id = fields.Many2one('res.users', string='Decided By', readonly=True)
    decided_on = fields.Datetime(string='Decided On', readonly=True)

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('partner_id', 'contract_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = _("%(member)s on %(contract)s",
                                 member=rec.partner_id.name, contract=rec.contract_id.name)

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_approve(self):
        """Add the member to the contract, which invites them to the portal."""

        self._bc_check_decidable()
        for rec in self:
            rec.contract_id.write({'contact_ids': [Command.link(rec.partner_id.id)]})
        self.write({'state': 'approved', 'decided_by_id': self.env.uid,
                    'decided_on': fields.Datetime.now()})
        self.activity_feedback([REVIEW_ACTIVITY], feedback=_("Approved"))
        for rec in self:
            rec._bc_tell_requester(_("%s was approved and has been invited to the portal.",
                                     rec.partner_id.name))

    def action_reject(self):
        """Refuse the request, with a reason the tenant's administrator is sent."""

        self._bc_check_decidable()
        if any(not (rec.reject_reason or '').strip() for rec in self):
            raise UserError(_("Write the Rejection Reason first; it is sent to the tenant's administrator."))
        self.write({'state': 'rejected', 'decided_by_id': self.env.uid,
                    'decided_on': fields.Datetime.now()})
        self.activity_feedback([REVIEW_ACTIVITY], feedback=_("Rejected"))
        for rec in self:
            rec._bc_tell_requester(_("%(member)s was not added to %(contract)s: %(reason)s",
                                     member=rec.partner_id.name, contract=rec.contract_id.name,
                                     reason=rec.reject_reason))

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _bc_check_decidable(self):
        """Only a Business Center Manager decides, and only once."""

        if not self.env.user.has_group('business_center.group_bc_manager'):
            raise UserError(_("Only a Business Center Manager can approve or reject team members."))
        if any(rec.state != 'pending' for rec in self):
            raise UserError(_("This request has already been decided."))

    def _bc_reviewer(self):
        """Who decides: the contract centre's manager, else the company's first
        Business Center Manager. Never a portal user."""

        self.ensure_one()
        manager = self.contract_id.center_id.manager_id
        if manager and manager.active and not manager.share:
            return manager
        managers = self.env['res.users'].sudo().search(
            [('share', '=', False), ('company_ids', 'in', self.company_id.ids)], order='id'
        ).filtered(lambda u: u.has_group('business_center.group_bc_manager'))
        return managers[:1] or self.env.ref('base.user_admin')

    def _bc_request_review(self):
        """Ask the reviewer to approve or reject."""

        for rec in self:
            rec.activity_schedule(
                REVIEW_ACTIVITY,
                summary=_("Review team member: %s", rec.partner_id.name),
                note=_("%(admin)s (%(tenant)s) wants to add %(member)s to %(contract)s. "
                       "Approve, or write a reason and reject.",
                       admin=rec.requested_by_id.name, tenant=rec.tenant_id.name,
                       member=rec.partner_id.name, contract=rec.contract_id.name),
                user_id=rec._bc_reviewer().id,
            )

    def _bc_tell_requester(self, body):
        """Email the decision to the administrator who asked, and keep it here."""

        self.ensure_one()
        self.message_post(body=body, partner_ids=self.requested_by_id.partner_id.ids,
                          subtype_xmlid='mail.mt_comment')