# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class BusinessCenterBookingCancelWizard(models.TransientModel):
    """Manager decision for cancelling a booking that has already started."""

    _name = 'business.center.booking.cancel.wizard'
    _description = 'Cancel a Started Booking'
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

    booking_id = fields.Many2one('business.center.booking', string='Booking',
                                 required=True, readonly=True, ondelete='cascade')
    booking_date = fields.Date(related='booking_id.booking_date')
    booked_slot_display = fields.Char(related='booking_id.selected_slot_display',
                                      string='Booked Slot')

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('outcome', 'used_until', 'booking_id')
    def _compute_billable_hours_display(self):
        """Preview how much of the booked slot will be billed for the chosen outcome."""

        for wiz in self:
            booking = wiz.booking_id
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
        """Cancel the booking with the chosen outcome and log the decision."""

        self.ensure_one()
        if not self.env.user.has_group('business_center.group_bc_manager'):
            raise UserError(_("Only a Business Center Manager can cancel a started booking."))
        booking = self.booking_id
        if booking.state != 'confirmed':
            raise UserError(_("Only a confirmed booking can be cancelled here."))
        if self.outcome == 'used' and not (
                booking.start_time < self.used_until < booking.end_time):
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
            _("Cancelled after start:"), outcome_label,
            _("Reason:"), self.reason,
        ))
        return {'type': 'ir.actions.act_window_close'}