# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError, UserError
from odoo.tools import float_is_zero, format_date
import logging

_logger = logging.getLogger(__name__)


class BusinessCenterBooking(models.Model):
    """Stores master records for business center bookings"""
    
    _name = 'business.center.booking'
    _description = 'A central registry of business center bookings'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'business.center.slot.booking.mixin']
    _order = 'name desc'

    # What the shared slot rules book: the meeting room, open per its own hours.
    _slot_resource_field = 'meeting_room_id'
    _slot_hours_path = 'meeting_room_id'
    _slot_blocking_states = ('confirmed',)
    
    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    user_id = fields.Many2one('res.users', string='Booked By', copy=False, index=True,
                              default=lambda self: self.env.user,
                              help="Who made this booking")
    name = fields.Char(string='Booking', required=True, copy=False, readonly=False, 
                       index='trigram', default=lambda self: _('New'))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled')
    ], default='draft', tracking=True)
    total_wallet_credits = fields.Float(string='Wallet Credit (hrs)', compute='_compute_total_wallet_credits')
    balance_wallet_credits = fields.Float(string='Balance Credits', compute='_compute_balance_wallet_credits')
    operating_time = fields.Char(related='meeting_room_id.operating_hours_display', string='Available Time')
    charge_per_hr = fields.Monetary(string='Hourly Rate', related='meeting_room_id.hourly_rate')
    chargeable_hours = fields.Float(string='Chargeable Hours', compute='_compute_chargeable_hours', store=True)
    wallet_balance_at_booking = fields.Float(string='Wallet Snapshot', copy=False)
    wallet_period_date = fields.Date(string='Wallet Period', copy=False, readonly=True, 
                                     help="Which wallet period this booking drew its hours from. Used to "
                                     "decide whether a cancellation can refund them.")
    wallet_balance_after_booking = fields.Float(string='Balance After Booking', copy=False)
    cancel_outcome = fields.Selection([
        ('waive', 'Charges Waived'),
        ('used', 'Time Used Charged'),
        ('full', 'Charged in Full'),
    ], string='Cancellation Outcome', readonly=True, copy=False, tracking=True,
        help="Set when a manager cancels a booking after it started.")
    cancel_reason = fields.Text(string='Cancellation Reason', readonly=True, copy=False)
    cancelled_by_id = fields.Many2one('res.users', string='Cancelled By', readonly=True, copy=False)
    original_end_time = fields.Float(string='Originally Booked Until', readonly=True, copy=False,
                                     help="Booked end time before a 'time used' cancellation "
                                          "shortened the booking.")
    overage_amount = fields.Monetary(string='Extra Charge', compute='_compute_overage_amount',
                                 currency_field='currency_id')
    chargeable_hours_display = fields.Char(string='Chargeable Time',
                                           compute='_compute_chargeable_hours_display')
    
    contract_id = fields.Many2one('business.center.contract', string='Contract',
                                  required=True, index=True, tracking=True,
                                  domain="[('state', '=', 'active'), "
                                         "('is_wallet_eligible', '=', True)]",
                                  help="Booking is made against the contract. Its "
                                       "centre decides which meeting rooms are offered. "
                                       "Desk-only contracts cannot book rooms.")
    center_id = fields.Many2one('business.center', string='Business Center',
                                related='contract_id.center_id', store=True)
    meeting_room_id = fields.Many2one(
        'business.center.space', string='Meeting Room', required=True,
        domain="[('space_type', '=', 'meeting_room'), "
               "('center_id', '=', center_id), "
               "('is_bookable', '=', True), "
               "('state', 'in', ('available', 'occupied'))]")
    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id)
    company_id = fields.Many2one(related='contract_id.company_id', store=True, string='Company')
    
    _no_double_booking = models.Constraint(
        """EXCLUDE USING gist (
               meeting_room_id WITH =,
               booking_date WITH =,
               numrange(start_time::numeric, end_time::numeric) WITH &&
           ) WHERE (state = 'confirmed')""",
        "This meeting room is already booked for part of that time slot.",
    )
    _STATE_ACTIONS = {
        'draft': 'action_reset_to_draft',
        'confirmed': 'action_confirm',
        'cancelled': 'action_cancel',
    }
    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------      
    @api.depends('contract_id', 'contract_id.wallet_balance',
                 'contract_id.is_wallet_eligible',
                 'state', 'wallet_balance_at_booking')
    def _compute_total_wallet_credits(self):
        """Wallet credits available for this booking. While draft, read the
        contract's live shared wallet so it tracks any changes. Once confirmed,
        read the balance saved at confirmation so the figure reflects the wallet
        as it was then, not as it stands now."""

        for booking in self:
            if booking.state == 'confirmed':
                booking.total_wallet_credits = booking.wallet_balance_at_booking
            elif booking.contract_id.is_wallet_eligible:
                booking.total_wallet_credits = booking.contract_id.wallet_balance
            else:
                booking.total_wallet_credits = 0.0
            
    @api.depends('chargeable_hours', 'charge_per_hr')
    def _compute_overage_amount(self):
        """Compute the extra charge as chargeable hours times the room's hourly rate."""
        
        for rec in self:
            rec.overage_amount = rec.chargeable_hours * rec.charge_per_hr
            
    @api.depends('total_wallet_credits', 'start_time', 'end_time', 'state',
                 'wallet_balance_after_booking')
    def _compute_balance_wallet_credits(self):
        """Wallet credits left after this booking. While draft, subtract the booked
        hours from the available credits as a live preview. Once confirmed, read the
        balance saved at confirmation so it reflects the wallet as it was then."""
        
        for rec in self:
            if rec.state == 'confirmed':
                # frozen: the balance left after this booking was applied
                rec.balance_wallet_credits = rec.wallet_balance_after_booking
            else:
                used = rec.end_time - rec.start_time if rec.end_time > rec.start_time else 0.0
                remaining = rec.total_wallet_credits - used
                rec.balance_wallet_credits = remaining if remaining >= 0 else 0.0
            
    @api.depends('total_wallet_credits', 'start_time', 'end_time', 'state',
                 'wallet_balance_at_booking', 'cancel_outcome')
    def _compute_chargeable_hours(self):
        """Compute the hours billed beyond available wallet credits: live against the
        current wallet while draft, against the frozen snapshot once confirmed.
        A cancelled booking is chargeable only if a manager kept its charges."""

        for rec in self:
            if rec.state == 'cancelled' and rec.cancel_outcome not in ('used', 'full'):
                rec.chargeable_hours = 0.0
                continue
            used = rec.end_time - rec.start_time if rec.end_time > rec.start_time else 0.0
            if rec.state == 'draft':
                # live preview against the wallet as it stands now
                available = rec.total_wallet_credits
            else:
                # frozen: use the balance captured at confirmation
                available = rec.wallet_balance_at_booking
            remaining = used - available
            rec.chargeable_hours = remaining if remaining > 0 else 0.0
            
    @api.depends('chargeable_hours')
    def _compute_chargeable_hours_display(self):
        """Show the chargeable hours as hours and minutes, e.g. '50 min'."""

        for rec in self:
            rec.chargeable_hours_display = rec._float_to_duration(rec.chargeable_hours)
            
    @api.model_create_multi
    def create(self, vals_list):
        """Assign a sequence reference (e.g. BK/2026/00001) to new bookings unless a
        name was explicitly provided."""
        
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft':
                raise UserError(_(
                    "A booking is created in Draft and confirmed through the "
                    "Confirm action, which draws the wallet hours and raises "
                    "any overage. Setting the status directly on create would "
                    "skip all of it."))
            if vals.get('name', _("New")) == _("New"):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'business.center.booking') or _("New")
        return super().create(vals_list)
    
    def write(self, vals):
        """Guard the state field, and keep non-managers out of confirmed bookings.

        Every state transition carries side effects - drawing wallet hours,
        raising or voiding an overage charge, refunding on cancel - and all of
        them live in the action_* methods. A bare write({'state': ...}) from a
        list view, a server action, an import or the ORM would skip the lot, so
        such a write is re-dispatched to the action that owns the transition.
        The actions write the state back through here with bc_state_from_action
        in the context, which is what stops the recursion.
        """

        if 'state' in vals and not self.env.context.get('bc_state_from_action'):
            target = vals['state']
            method = self._STATE_ACTIONS.get(target)
            if not method:
                raise UserError(_("Unknown booking status: %s") % target)
            others = {k: v for k, v in vals.items() if k != 'state'}
            if others:
                self.write(others)
            for booking in self:
                if booking.state != target:
                    getattr(booking, method)()
                    if booking.state != target:
                        # A started booking returns the cancel wizard instead of
                        # cancelling; a bare write cannot show it, so refuse
                        # rather than silently doing nothing.
                        raise UserError(_(
                            "%s has already started. Use the Cancel button on the "
                            "booking to record the outcome.", booking.name))
            return True

        if not self.env.user.has_group('business_center.group_bc_manager'):
            for booking in self:
                if booking.state != 'draft' and set(vals) - {'state'}:
                    raise UserError(_("A confirmed booking can only be cancelled."))
        return super().write(vals)
    
    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------
    @api.onchange('contract_id')
    def _onchange_contract_clear_room(self):
        """Drop a room that belongs to another centre when the contract changes,
        so the picked room always matches the contract's centre."""

        if (self.meeting_room_id and self.contract_id.center_id
                and self.meeting_room_id.center_id != self.contract_id.center_id):
            self.meeting_room_id = False

    @api.constrains('meeting_room_id', 'contract_id')
    def _check_room_in_contract_center(self):
        """A contract can only book rooms in its own business centre."""

        for rec in self:
            center = rec.contract_id.center_id
            if not (rec.meeting_room_id and center):
                continue
            if rec.meeting_room_id.center_id != center:
                raise ValidationError(_(
                    "%(room)s is not in the same business center as contract "
                    "%(contract)s. Pick a room in %(center)s.",
                    room=rec.meeting_room_id.display_name,
                    contract=rec.contract_id.name,
                    center=center.display_name,
                ))    
                     
    @api.constrains('meeting_room_id')
    def _check_employee_meeting_room_only(self):
        """Only spaces flagged as bookable meeting rooms may be booked. The
        form domain filters the dropdown; this catches the portal, imports and
        any direct create()."""

        for booking in self:
            room = booking.meeting_room_id
            if not room:
                raise ValidationError(_("A booking must have a meeting room."))
            if room.space_type != 'meeting_room':
                raise ValidationError(_("You can only book meeting rooms."))
            if not room.is_bookable:
                raise ValidationError(_(
                    "%(room)s is not currently open for booking.",
                    room=room.display_name,
                ))
        
    @api.onchange('meeting_room_id')
    def _onchange_meeting_room_slot(self):
        """Re-check the slot against the newly picked room."""

        return self._slot_onchange_warning()

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_confirm(self):
        """Confirm the booking: draw the hours from the contract's wallet, raise an
        overage charge for anything beyond it, and freeze the wallet snapshots."""

        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Only a draft booking can be confirmed."))
        
        if not self.contract_id or self.contract_id.state != 'active':
            raise UserError(_(
                "Bookings can only be made against a running contract."))
            
        if not self.contract_id.is_wallet_eligible:
            raise UserError(_(
                "%(contract)s leases desks only, so it cannot book meeting "
                "rooms.", contract=self.contract_id.name))

        if self.meeting_room_id:
            self.env.cr.execute(
                "SELECT id FROM business_center_space WHERE id = %s FOR UPDATE",
                (self.meeting_room_id.id,))

        contract = self.contract_id
        if contract.center_id and self.meeting_room_id.center_id != contract.center_id:
            raise UserError(_(
                "%(room)s is not in %(center)s, where this contract's assets are.",
                room=self.meeting_room_id.display_name,
                center=contract.center_id.display_name))

        # Re-checked here, not just in the constraint: a booking may have sat in
        # draft since before the room was withdrawn, and an unchanged field does
        # not re-fire @api.constrains.
        if not self.meeting_room_id.is_bookable:
            raise UserError(_(
                "%(room)s has been withdrawn from booking.",
                room=self.meeting_room_id.display_name))
            
        if self._is_in_past() and not self.env.user.has_group(
                'business_center.group_bc_manager'):
            raise UserError(_(
                "%s starts in the past and cannot be confirmed. Ask a "
                "manager to record a past booking.", self.name))

        if self.meeting_room_id.state not in ('available', 'occupied'):
            raise UserError(_(
                "%(room)s is not available for booking (status: %(state)s).",
                room=self.meeting_room_id.display_name,
                state=dict(self.meeting_room_id._fields['state'].selection)[
                    self.meeting_room_id.state]))

        # Lock order stays: meeting room space first, then contract.
        self.env.cr.execute(
            "SELECT id FROM business_center_contract WHERE id = %s FOR UPDATE",
            (contract.id,))
        contract.invalidate_recordset(['wallet_balance'])

        hours = self._booking_hours()
        available = contract.wallet_balance if contract.is_wallet_eligible else 0.0
        self.wallet_balance_at_booking = available
        self.wallet_period_date = contract.last_wallet_reset_date

        if hours <= available:
            contract.wallet_balance = available - hours
        else:
            overage = hours - available
            if available:
                contract.wallet_balance = 0.0
            self._create_overage_charge(overage)

        self.wallet_balance_after_booking = contract.wallet_balance
        self.with_context(bc_state_from_action=True).write({'state': 'confirmed'})
        
    def action_cancel(self):
        """Cancel the booking. Before it starts this refunds its wallet hours and
        voids its overage. Once it has started only a manager can cancel it, and
        that goes through the wizard so the outcome and reason are recorded."""

        self.ensure_one()
        if self.state == 'cancelled':
            raise UserError(_("This booking is already cancelled."))

        is_manager = self.env.user.has_group('business_center.group_bc_manager')
        if self.state == 'confirmed':
            if self._is_in_past():
                if not is_manager:
                    raise UserError(_(
                        "%(booking)s started at %(start)s on %(date)s. Contact the "
                        "centre manager to cancel it.",
                        booking=self.name,
                        start=self._float_to_ampm(self.start_time),
                        date=format_date(self.env, self.booking_date),
                    ))
                return self.action_open_cancel_wizard()
            invoiced = self.contract_id.charge_ids.filtered(
                lambda c: c.booking_id == self and c.state == 'invoiced')
            if invoiced and not is_manager:
                raise UserError(_(
                    "The overage on %s is already on an invoice. Ask a manager "
                    "to cancel this booking.", self.name))
        self._apply_cancellation()

    def action_open_cancel_wizard(self):
        """Open the manager's wizard for cancelling a booking that has started,
        with 'used until' defaulting to now, kept within the booked slot."""

        self.ensure_one()
        now = self._local_now()
        if self.booking_date == now.date():
            now_hours = now.hour + now.minute / 60.0
            used_until = min(max(now_hours, self.start_time), self.end_time)
        else:
            used_until = self.end_time
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cancel Started Booking'),
            'res_model': 'business.center.booking.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_booking_id': self.id,
                'default_used_until': used_until,
            },
        }
        
    def action_reset_to_draft(self):
        """Reset to draft, reversing any wallet draw and overage charge first."""

        self.ensure_one()
        if not self.env.user.has_group('business_center.group_bc_manager'):
            raise UserError(_("Only a Business Center Manager can reset a booking."))
        if self.state == 'confirmed' and self._is_in_past():
            raise UserError(_(
                "%s has already started. Cancel it to record the outcome "
                "instead of resetting it.", self.name))
        if self.state == 'cancelled' and self.cancel_outcome in ('used', 'full'):
            raise UserError(_(
                "%s was cancelled with its charges kept, so it cannot be "
                "reset. Create a new booking instead.", self.name))
        if self.state == 'confirmed':
            contract = self.contract_id
            wallet_used = self.wallet_balance_at_booking - self.wallet_balance_after_booking
            if contract and wallet_used > 0:
                contract.wallet_balance = min(
                    contract.wallet_balance + wallet_used,
                    contract.free_hours_monthly,
                )
            charges = self.contract_id.charge_ids.filtered(
                lambda c: c.booking_id == self and c.state == 'pending')
            if self.contract_id.charge_ids.filtered(
                    lambda c: c.booking_id == self and c.state == 'invoiced'):
                raise UserError(_(
                    "This booking's overage has already been invoiced and "
                    "cannot be reset. Cancel the booking instead."))
            charges.unlink()
        self.with_context(bc_state_from_action=True).write({
            'wallet_balance_at_booking': 0.0,
            'wallet_balance_after_booking': 0.0,
            'cancel_outcome': False,
            'cancel_reason': False,
            'cancelled_by_id': False,
            'original_end_time': 0.0,
            'state': 'draft',
        })
                
    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _apply_cancellation(self, outcome=False, reason=False, used_until=False):
        """Cancel the booking and settle its wallet hours and overage.

        outcome False / 'waive': nothing billable, everything refunded.
        'used': bill start -> used_until, and shorten the booking to that.
        'full': bill the whole booked slot.

        The billable hours are re-split against the wallet snapshot taken at
        confirmation: wallet hours no longer used go back to the wallet (same
        period only), and the overage charge is replaced only if its amount
        changed - so 'full' leaves an already-invoiced overage untouched.
        """

        self.ensure_one()
        vals = {'state': 'cancelled'}
        if outcome:
            vals.update({
                'cancel_outcome': outcome,
                'cancel_reason': reason,
                'cancelled_by_id': self.env.uid,
            })

        if self.state == 'confirmed':
            contract = self.contract_id
            if outcome == 'full':
                billable = self._booking_hours()
            elif outcome == 'used':
                billable = max(min(used_until, self.end_time) - self.start_time, 0.0)
            else:
                billable = 0.0

            self.env.cr.execute(
                "SELECT id FROM business_center_contract WHERE id = %s FOR UPDATE",
                (contract.id,))
            contract.invalidate_recordset(['wallet_balance'])

            # Re-split the billable hours against the wallet as it was at confirmation.
            new_wallet_hours = min(billable, self.wallet_balance_at_booking)
            new_overage = billable - new_wallet_hours

            charges = contract.charge_ids.filtered(
                lambda c: c.booking_id == self and c.state in ('pending', 'invoiced'))
            old_overage = sum(charges.mapped('quantity'))
            if not float_is_zero(new_overage - old_overage, precision_digits=4):
                posted = charges.filtered(
                    lambda c: c.state == 'invoiced'
                    and c.invoice_line_id.move_id.state == 'posted')
                if posted:
                    raise UserError(_(
                        "The overage on %(booking)s is on posted invoice "
                        "%(invoice)s and cannot be changed. Issue a credit note "
                        "instead.",
                        booking=self.name,
                        invoice=posted[0].invoice_line_id.move_id.name,
                    ))
                # Still-draft invoice: pull the line before voiding the charge.
                charges.filtered(lambda c: c.state == 'invoiced').invoice_line_id.unlink()
                charges.sudo().write({'state': 'cancelled', 'invoice_line_id': False})
                if new_overage > 0:
                    self._create_overage_charge(new_overage)

            wallet_used = self.wallet_balance_at_booking - self.wallet_balance_after_booking
            refund = wallet_used - new_wallet_hours
            same_period = (
                self.wallet_period_date
                and contract.last_wallet_reset_date == self.wallet_period_date
            )
            if refund > 0 and same_period:
                contract.wallet_balance = min(
                    contract.wallet_balance + refund,
                    contract.free_hours_monthly,
                )
            elif refund > 0:
                _logger.info(
                    "Booking %s cancelled after a wallet reset; %s hour(s) "
                    "lapsed with the previous period and were not refunded.",
                    self.name, refund)

            if outcome == 'used':
                vals.update({
                    'original_end_time': self.end_time,
                    'end_time': self.start_time + billable,
                })

        self.with_context(bc_state_from_action=True).write(vals)
    
    def _create_overage_charge(self, overage_hours):
        """Raise a pending contract charge for the meeting-room hours over wallet credit."""
        
        self.ensure_one()
        if overage_hours <= 0:
            return
        self.env['business.center.contract.charge'].sudo().create({
            'date': self.booking_date or fields.Date.context_today(self),
            'description': 'Meeting room credits overage',
            'booking_id': self.id,
            'contract_id': self.contract_id.id,
            'quantity': overage_hours,
            'unit_price': self.charge_per_hr,
        })
