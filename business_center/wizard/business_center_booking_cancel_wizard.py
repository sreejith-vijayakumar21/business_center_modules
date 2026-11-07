# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Booking models the wizard settles; each implements _bc_check_settle and
# _apply_cancellation(outcome, reason, used_until).
BOOKING_MODELS = [
    ('business.center.booking', 'Meeting Room Booking'),
    ('business.center.desk.booking', 'Hot Desk Booking'),
]


class BusinessCenterBookingCancelWizard(models.TransientModel):
    """Manager's charge decision for a booking: cancelling one that has
    already started, or settling a hot desk released or not shown up for.

    The wizard only collects the decision; the booking applies it through
    its own _apply_cancellation, so meeting rooms (wallet, overage) and hot
    desks (contract charge, invoice) each settle their own way.
    """

    _name = 'business.center.booking.cancel.wizard'
    _description = 'Booking Charge Decision'
    _inherit = ['business.center.time.format.mixin']

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    outcome = fields.Selection([
        ('waive', 'Waive all charges'),
        ('used', 'Charge time used only'),
        ('full', 'Charge in full'),
    ], string='Outcome', required=True, default='waive')
    reason = fields.Text(string='Reason', required=True)
    used_until = fields.Float(string='Used Until')
    billable_hours_display = fields.Char(string='Billable Time',
                                         compute='_compute_billable_hours_display')

    booking_ref = fields.Reference(BOOKING_MODELS, string='Booking', required=True, readonly=True)
    booking_date = fields.Date(string='Date', compute='_compute_booking_info')
    booked_slot_display = fields.Char(string='Booked Slot', compute='_compute_booking_info')

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('booking_ref')
    def _compute_booking_info(self):
        """Date and slot of the booking being settled."""

        for wiz in self:
            wiz.booking_date = wiz.booking_ref.booking_date if wiz.booking_ref else False
            wiz.booked_slot_display = wiz.booking_ref.selected_slot_display if wiz.booking_ref else False

    @api.depends('outcome', 'used_until', 'booking_ref')
    def _compute_billable_hours_display(self):
        """Preview how much of the booked slot will be billed for the chosen outcome."""

        for wiz in self:
            booking = wiz.booking_ref
            if not booking:
                wiz.billable_hours_display = False
                continue
            if wiz.outcome == 'full':
                hours = booking._booking_hours()
            elif wiz.outcome == 'used':
                hours = max(min(wiz.used_until, booking.end_time) - booking.start_time, 0.0)
            else:
                hours = 0.0
            wiz.billable_hours_display = wiz._float_to_duration(hours)

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_confirm(self):
        """Apply the decision to the booking and log it."""

        self.ensure_one()
        if not self.env.user.has_group('business_center.group_bc_manager'):
            raise UserError(_("Only a Business Center Manager can decide a booking's charge."))
        booking = self.booking_ref
        booking._bc_check_settle()
        if self.outcome == 'used' and not (booking.start_time < self.used_until < booking.end_time):
            raise UserError(_(
                "'Used Until' must fall inside the booked slot (%(start)s - %(end)s). "
                "For nothing used choose 'Waive all charges'; for the whole slot "
                "choose 'Charge in full'.",
                start=self._float_to_ampm(booking.start_time),
                end=self._float_to_ampm(booking.end_time),
            ))

        booking._apply_cancellation(self.outcome, self.reason, self.used_until)

        outcome_label = dict(self._fields['outcome'].selection)[self.outcome]
        if self.outcome == 'used':
            outcome_label = _("%(label)s (until %(time)s)", label=outcome_label,
                              time=self._float_to_ampm(self.used_until))
        booking.message_post(body=Markup("<p><b>%s</b> %s</p><p>%s %s</p>") % (
            _("Charge decision:"), outcome_label,
            _("Reason:"), self.reason,
        ))
        return {'type': 'ir.actions.act_window_close'}
