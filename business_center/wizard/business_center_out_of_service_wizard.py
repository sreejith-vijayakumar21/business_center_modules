# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, fields, models
from odoo.exceptions import UserError

ASSET_MODELS = [
    ('business.center.space', 'Space'),
    ('business.center.desk', 'Desk'),
]


class BusinessCenterOutOfServiceWizard(models.TransientModel):
    """Why a space or desk leaves service (Draft or Maintenance).

    The wizard only collects the reason; the asset checks nobody holds it,
    records the reason and changes its own state."""

    _name = 'business.center.out.of.service.wizard'
    _description = 'Take a Space or Desk Out of Service'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    asset_ref = fields.Reference(ASSET_MODELS, string='Asset', required=True, readonly=True)
    target_state = fields.Selection([
        ('draft', 'Draft (structural change)'),
        ('maintenance', 'Maintenance (repair)'),
    ], string='Take To', required=True, default='draft')
    reason = fields.Char(string='Reason', required=True)

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_confirm(self):
        """Take the asset out of service with the given reason."""

        self.ensure_one()
        if not self.env.user.has_group('business_center.group_bc_manager'):
            raise UserError(_("Only a Business Center Manager can take an asset out of service."))
        asset = self.asset_ref
        if self.target_state == 'maintenance':
            asset.action_set_maintenance()
        else:
            asset.action_set_draft()
        asset._bc_take_out_of_service(self.reason)
        return {'type': 'ir.actions.act_window_close'}
