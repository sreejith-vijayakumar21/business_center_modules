# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class BusinessCenterContract(models.Model):
    _inherit = 'business.center.contract'

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _bc_ticket_units(self):
        """The places a ticket on this contract may be about: the offices and
        desks it leases, and the meeting rooms of its centre. Returns
        (spaces, desks)."""

        self.ensure_one()
        assets = self.leased_asset_ids
        spaces = assets.space_id
        if self.center_id:
            spaces |= self.env['business.center.space'].search([
                ('center_id', '=', self.center_id.id),
                ('space_type', '=', 'meeting_room'),
            ])
        return spaces, assets.desk_id
