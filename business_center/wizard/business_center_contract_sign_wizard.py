# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, fields, models
from odoo.exceptions import UserError


class BusinessCenterContractSignWizard(models.TransientModel):
    """Record a lease agreement signed on paper and returned by the tenant."""

    _name = 'business.center.contract.sign.wizard'
    _description = 'Record Signed Lease Agreement'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    signed_by = fields.Char(string='Signed By', required=True)
    signed_on = fields.Date(string='Signed On', required=True,
                            default=fields.Date.context_today)
    signed_file = fields.Binary(string='Signed Copy', required=True)
    signed_filename = fields.Char(string='File Name')

    contract_id = fields.Many2one('business.center.contract', string='Contract',
                                  required=True, readonly=True)

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_confirm(self):
        """Attach the signed copy to the contract and mark it signed."""

        self.ensure_one()
        contract = self.contract_id
        contract._check_bc_manager()
        if self.signed_on > fields.Date.context_today(self):
            raise UserError(_("The signing date cannot be in the future."))
        attachment = self.env['ir.attachment'].create({
            'name': self.signed_filename or _(
                "Signed Agreement - %s.pdf", contract.name.replace('/', '-')),
            'datas': self.signed_file,
            'res_model': contract._name,
            'res_id': contract.id,
        })
        contract._mark_agreement_signed(self.signed_by, self.signed_on,
                                        attachment=attachment)
        return {'type': 'ir.actions.act_window_close'}