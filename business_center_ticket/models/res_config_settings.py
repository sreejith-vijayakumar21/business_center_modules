# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    bc_ticket_hours_urgent = fields.Integer(
        related='company_id.bc_ticket_hours_urgent', readonly=False)
    bc_ticket_hours_high = fields.Integer(
        related='company_id.bc_ticket_hours_high', readonly=False)
    bc_ticket_hours_normal = fields.Integer(
        related='company_id.bc_ticket_hours_normal', readonly=False)
    bc_ticket_hours_low = fields.Integer(
        related='company_id.bc_ticket_hours_low', readonly=False)
    bc_ticket_reopen_days = fields.Integer(
        related='company_id.bc_ticket_reopen_days', readonly=False)
