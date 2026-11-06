# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models

from odoo.exceptions import ValidationError 


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
    bc_hot_desk_reminder_minutes = fields.Integer(
        string='Send Reminder After (min)', default=10,
        help="Minutes after a hot desk booking starts, without check-in, before "
             "the customer is asked whether they are still coming.")
    bc_hot_desk_checkin_grace = fields.Integer(
        string='Release Unattended Desk After (min)', default=30,
        help="Minutes after the start, without check-in or an answer, before "
             "the desk is released and the booking becomes a no-show.")
    bc_hot_desk_late_release_charge = fields.Selection([
        ('none', 'No Charge'),
        ('first_hour', 'First Hour'),
        ('full', 'Full Booking'),
    ], string='Late Release Charge', default='none', required=True,
        help="What a booking released by the customer after it started is charged.")
    
    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------
    @api.constrains('bc_hot_desk_reminder_minutes', 'bc_hot_desk_checkin_grace')
    def _check_hot_desk_policy(self):
        """The reminder must go out before the desk is released."""

        for company in self:
            if company.bc_hot_desk_reminder_minutes < 0 or company.bc_hot_desk_checkin_grace <= 0:
                raise ValidationError(_("Hot desk reminder and release times must be positive."))
            if company.bc_hot_desk_reminder_minutes >= company.bc_hot_desk_checkin_grace:
                raise ValidationError(_(
                    "The hot desk reminder (%(reminder)s min) must come before the "
                    "release (%(release)s min).",
                    reminder=company.bc_hot_desk_reminder_minutes,
                    release=company.bc_hot_desk_checkin_grace))
