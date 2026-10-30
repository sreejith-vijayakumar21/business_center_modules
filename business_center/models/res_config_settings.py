# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    bc_expiry_reminder_days = fields.Integer(
        string='Expiry Reminder Lead Days',
        related='company_id.bc_expiry_reminder_days',
        readonly=False,
        help="Default number of days before a contract's end date that the "
             "renewal reminder goes out. Can be overridden per contract.")
    bc_timezone = fields.Selection(
        related='company_id.partner_id.tz', readonly=False,
        string='Business Centre Timezone',
        help="Local time of the buildings. Contract start and end dates, the "
             "nightly contract and billing runs, and booking dates and times "
             "are all decided in this timezone, including for portal users.")
    bc_renewal_increase_pct = fields.Float(
        related='company_id.bc_renewal_increase_pct', readonly=False)
    bc_invoice_auto_send = fields.Boolean(
        related='company_id.bc_invoice_auto_send', readonly=False)
