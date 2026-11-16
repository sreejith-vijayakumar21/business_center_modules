# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    bc_ticket_hours_urgent = fields.Integer(
        string='Urgent Ticket Target (h)', default=4,
        help="Hours within which an urgent ticket should be resolved.")
    bc_ticket_hours_high = fields.Integer(
        string='High Priority Ticket Target (h)', default=8,
        help="Hours within which a high priority ticket should be resolved.")
    bc_ticket_hours_normal = fields.Integer(
        string='Normal Ticket Target (h)', default=24,
        help="Hours within which a normal ticket should be resolved.")
    bc_ticket_hours_low = fields.Integer(
        string='Low Priority Ticket Target (h)', default=72,
        help="Hours within which a low priority ticket should be resolved.")
    bc_ticket_reopen_days = fields.Integer(
        string='Ticket Reopen Window (days)', default=7,
        help="Days after a ticket is resolved during which the member can "
             "reopen it. After that it is closed automatically.")

    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------
    @api.constrains('bc_ticket_hours_urgent', 'bc_ticket_hours_high', 'bc_ticket_hours_normal',
                    'bc_ticket_hours_low', 'bc_ticket_reopen_days')
    def _check_ticket_policy(self):
        """Targets must be positive; the reopen window may be zero (no reopening)."""

        for company in self:
            targets = (company.bc_ticket_hours_urgent, company.bc_ticket_hours_high,
                       company.bc_ticket_hours_normal, company.bc_ticket_hours_low)
            if min(targets) <= 0:
                raise ValidationError(_("Ticket response targets must be at least one hour."))
            if company.bc_ticket_reopen_days < 0:
                raise ValidationError(_("The ticket reopen window cannot be negative."))
