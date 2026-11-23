# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MEMBERSHIP_STATES = [
    ('none', 'No Membership'),
    ('upcoming', 'Upcoming'),
    ('active', 'Active'),
    ('expiring', 'Expiring Soon'),
    ('expired', 'Expired'),
]
BC_USER_GROUP = 'business_center.group_bc_user'


class ResPartner(models.Model):
    """Membership status of a contact, read from the tenant company's
    contracts. The contract is the membership, so nothing is stored here:
    the rule lives on business.center.contract and this only shows it."""

    _inherit = 'res.partner'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    bc_membership_state = fields.Selection(
        MEMBERSHIP_STATES, string='Membership', groups=BC_USER_GROUP,
        compute='_compute_bc_membership', search='_search_bc_membership_state',
        help="Status of the company's business centre membership. Employees "
             "share their company's status.")
    bc_member_since = fields.Date(
        string='Member Since', groups=BC_USER_GROUP, compute='_compute_bc_membership',
        help="Start of the company's first contract that has begun.")
    bc_membership_starts_on = fields.Date(
        string='Membership Starts', groups=BC_USER_GROUP, compute='_compute_bc_membership')
    bc_membership_valid_until = fields.Date(
        string='Valid Until', groups=BC_USER_GROUP, compute='_compute_bc_membership',
        help="Last day covered by running contracts, including a renewal that "
             "follows straight on. For an expired membership, the day it ended.")
    bc_membership_contract_id = fields.Many2one(
        'business.center.contract', string='Current Contract', groups=BC_USER_GROUP,
        compute='_compute_bc_membership')
    bc_membership_center_ids = fields.Many2many(
        'business.center', string='Centres', groups=BC_USER_GROUP,
        compute='_compute_bc_membership')
    bc_membership_named = fields.Boolean(
        string='Named on Contract', groups=BC_USER_GROUP, compute='_compute_bc_membership',
        help="Listed as an employee on a running contract, which lets this "
             "person book desks and meeting rooms.")
    bc_contract_count = fields.Integer(
        string='Contracts', groups=BC_USER_GROUP, compute='_compute_bc_contract_count')

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('commercial_partner_id')
    def _compute_bc_membership(self):
        """One contract search for the whole batch; ``_origin`` so a contact
        being edited in the form still reads its saved company."""

        Contract = self.env['business.center.contract']
        partners = self._origin
        summaries = Contract._bc_membership_by_company(partners.commercial_partner_id)
        named_ids = Contract._bc_named_contact_ids(partners)
        empty = Contract.browse()._bc_membership_summary()
        for partner in self:
            summary = summaries.get(partner._origin.commercial_partner_id.id, empty)
            partner.bc_membership_state = summary['state']
            partner.bc_member_since = summary['member_since']
            partner.bc_membership_starts_on = summary['starts_on']
            partner.bc_membership_valid_until = summary['valid_until']
            partner.bc_membership_contract_id = summary['contract']
            partner.bc_membership_center_ids = summary['centers']
            partner.bc_membership_named = partner._origin.id in named_ids

    @api.depends('commercial_partner_id')
    def _compute_bc_contract_count(self):
        """Contracts of the company, so an employee's button opens them too."""

        counts = self.env['business.center.contract']._bc_contract_count_by_company(
            self._origin.commercial_partner_id)
        for partner in self:
            partner.bc_contract_count = counts.get(partner._origin.commercial_partner_id.id, 0)

    def _search_bc_membership_state(self, operator, value):
        """Let the contact list filter on the computed status: work out the
        state of every member company, then match contacts through their
        commercial partner. Companies without a membership are 'none'."""

        if operator not in ('=', '!=', 'in', 'not in'):
            raise UserError(_("Membership can only be filtered by its status."))
        wanted = set(value) if operator in ('in', 'not in') else {value}
        wanted = {state or 'none' for state in wanted}
        summaries = self.env['business.center.contract']._bc_membership_by_company()
        matching = [cid for cid, summary in summaries.items() if summary['state'] in wanted]
        domain = [('commercial_partner_id', 'in', matching)]
        if 'none' in wanted:
            domain = ['|'] + domain + [('commercial_partner_id', 'not in', list(summaries))]
        return ['!'] + domain if operator in ('!=', 'not in') else domain

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_view_bc_contracts(self):
        """Open the company's contracts from the contact's smart button."""

        self.ensure_one()
        company = self.commercial_partner_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contracts'),
            'res_model': 'business.center.contract',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', company.id)],
            'context': {'default_partner_id': company.id},
        }