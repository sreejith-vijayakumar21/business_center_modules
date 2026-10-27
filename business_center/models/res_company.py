# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    bc_expiry_reminder_days = fields.Integer(
        string='Expiry Reminder Lead Days', default=30,
        help="Days before a contract ends that the renewal reminder is sent, "
             "unless the contract overrides it.")
    bc_renewal_increase_pct = fields.Float(
        string='Default Renewal Rent Increase (%)', default=0.0,
        help="Rent increase applied when a contract renews, unless the contract "
             "sets its own. Use 0 to renew at the same rent.")
