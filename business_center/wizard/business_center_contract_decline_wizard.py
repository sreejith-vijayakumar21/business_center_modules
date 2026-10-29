# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, fields, models
from odoo.exceptions import UserError


class BusinessCenterContractDeclineWizard(models.TransientModel):
    """Record a tenant's refusal of the lease agreement and decide what
    happens to the contract: revise it, or cancel it."""

    _name = 'business.center.contract.decline.wizard'
    _description = 'Record Declined Lease Agreement'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    reason = fields.Text(string='Reason', required=True,
                         help="What the tenant objected to, kept in the chatter.")

    contract_id = fields.Many2one('business.center.contract', string='Contract',
                                  required=True, readonly=True)

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _log_decline(self):
        """Close the signature follow-up and record the reason on the contract."""

        self.ensure_one()
        contract = self.contract_id
        contract._check_bc_manager()
        if contract.agreement_state != 'sent':
            raise UserError(_("Only an agreement awaiting signature can be declined."))
        contract.activity_feedback(
            ['business_center.mail_activity_type_contract_signature'],
            feedback=_("Tenant declined: %s", self.reason))
        contract.message_post(body=_("Tenant declined the agreement: %s", self.reason))
        return contract

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_revise(self):
        """Send the contract back to draft so it can be changed and confirmed
        again, which sends a fresh agreement."""

        contract = self._log_decline()
        contract.action_set_draft()
        return {'type': 'ir.actions.act_window_close'}

    def action_cancel_contract(self):
        """The tenant is not taking the space: cancel and release it."""

        contract = self._log_decline()
        contract.agreement_state = 'declined'
        contract.action_set_cancel()
        return {'type': 'ir.actions.act_window_close'}