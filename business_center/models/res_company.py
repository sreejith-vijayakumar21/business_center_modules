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
    bc_invoice_auto_send = fields.Boolean(
        string='Post and Email Invoices Automatically', default=False,
                help="When the monthly billing run creates a contract invoice, confirm "
             "it and email it to the tenant. Leave off to review drafts first. "
             "A contract can opt out with Review Invoices Manually.")
    bc_hot_desk_no_show_charge = fields.Selection([
        ('none', 'No Charge'),
        ('first_hour', 'First Hour'),
        ('full', 'Full Booking'),
    ], string='Hot Desk No-show Charge', default='first_hour', required=True,
        help="What a hot desk booking nobody checked in to is charged.")
    bc_hot_desk_checkin_grace = fields.Integer(
        string='Hot Desk Check-in Grace (min)', default=15,
        help="Minutes after the start before an unchecked booking becomes a no-show.")
