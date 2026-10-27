# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class AccountMove(models.Model):
    """Link invoices back to the business center contract they bill"""

    _inherit = 'account.move'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    bc_contract_id = fields.Many2one('business.center.contract', string='Business Contract')