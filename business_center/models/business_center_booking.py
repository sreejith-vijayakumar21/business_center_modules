# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError, UserError
from odoo.tools import format_date
from markupsafe import escape
import logging

_logger = logging.getLogger(__name__)


class BusinessCenterBooking(models.Model):
    """Stores master records for business center bookings"""
    
    _name = 'business.center.booking'
    _description = 'A central registry of business center bookings'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'business.center.time.format.mixin']
    
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
    start_time = fields.Float(string='Start Time')
    end_time = fields.Float(string='End Time')
    selected_slot_display = fields.Char(string='Selected Slot', compute='_compute_selected_slot_display', 
                                         store=True)
    operating_time = fields.Char(related='meeting_room_id.operating_hours_display', string='Available Time')
    booking_date = fields.Date(string='Date', required=True)
    charge_per_hr = fields.Monetary(string='Hourly Rate', related='meeting_room_id.hourly_rate')
    chargeable_hours = fields.Float(string='Chargeable Hours', compute='_compute_chargeable_hours', store=True)
    wallet_balance_at_booking = fields.Float(string='Wallet Snapshot', copy=False)
    wallet_period_date = fields.Date(string='Wallet Period', copy=False, readonly=True, 
                                     help="Which wallet period this booking drew its hours from. Used to "
                                     "decide whether a cancellation can refund them.")
    wallet_balance_after_booking = fields.Float(string='Balance After Booking', copy=False)
    overage_amount = fields.Monetary(string='Extra Charge', compute='_compute_overage_amount',
                                 currency_field='currency_id')
    slot_availability_html = fields.Html(string='Slot Availability', compute='_compute_slot_availability_html', 
                                         sanitize=False)
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
            
    @api.depends('meeting_room_id', 'booking_date')
    def _compute_slot_availability_html(self):
        """Render the day's booking timeline as coloured slot boxes, splitting the
        operating window at every booking edge and marking each segment busy or free."""
        
        for rec in self:
            room = rec.meeting_room_id
            if not room or not rec.booking_date or not room.max_booking_hour:
                rec.slot_availability_html = False
                continue

            open_h = room.min_booking_hour or 0.0
            close_h = room.max_booking_hour

            domain = [
                ('meeting_room_id', '=', room.id),
                ('state', '=', 'confirmed'),
                ('booking_date', '=', rec.booking_date),
            ]
            if rec._origin.id:
                domain.append(('id', '!=', rec._origin.id))
            existing = self.search(domain)

            # 1. Build boundary points from the day edges + every booking edge,
            #    clamped to operating hours and de-duplicated.
            points = {open_h, close_h}
            for b in existing:
                if b.start_time > open_h and b.start_time < close_h:
                    points.add(b.start_time)
                if b.end_time > open_h and b.end_time < close_h:
                    points.add(b.end_time)
            points = sorted(points)

            # 2. Each consecutive pair is one segment; colour by whether a
            #    booking covers its midpoint.
            boxes = []
            for seg_start, seg_end in zip(points, points[1:]):
                if seg_end - seg_start < 0.001:
                    continue
                mid = (seg_start + seg_end) / 2.0
                booked = existing.filtered(
                    lambda b: b.start_time <= mid and b.end_time > mid
                )
                occupied = bool(booked)
                color = '#e74c8b' if occupied else '#7ed957'
                # Staff see the booking reference; portal users only see that
                # the slot is taken, not another tenant's booking number.
                if not occupied:
                    title = _('Available')
                elif self.env.user.share:
                    title = _('Booked')
                else:
                    title = booked[:1].name
                label = "%s – %s" % (
                    rec._float_to_ampm(seg_start),
                    rec._float_to_ampm(seg_end),
                )
                boxes.append(
                    "<div class='o_bc_slot %s' data-start='%s' data-end='%s' "
                    "title='%s' style='background:%s;color:#111;"
                    "padding:5px 8px;border-radius:5px;font-size:11px;"
                    "text-align:center;white-space:nowrap;'>%s</div>"
                    % ('o_bc_slot_busy' if occupied else 'o_bc_slot_free',
                       seg_start, seg_end, escape(title), color, label)
                )

            rec.slot_availability_html = (
                "<div style='display:flex;flex-wrap:wrap;gap:6px;'>%s</div>"
                % "".join(boxes)
            )
            
    @api.depends('total_wallet_credits', 'start_time', 'end_time', 'state', 'wallet_balance_at_booking')
    def _compute_chargeable_hours(self):
        """Compute the hours billed beyond available wallet credits: live against the
        current wallet while draft, against the frozen snapshot once confirmed."""
        
        for rec in self:
            if rec.state == 'cancelled':
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
            return True

        if not self.env.user.has_group('business_center.group_bc_manager'):
            for booking in self:
                if booking.state != 'draft' and set(vals) - {'state'}:
                    raise UserError(_("A confirmed booking can only be cancelled."))
        return super().write(vals)
    
    @api.depends('start_time', 'end_time')
    def _compute_selected_slot_display(self):
        """Builds a human-readable selected slot time.For Meeting Rooms, 
        formats time slots in AM/PM notation"""
            
        for rec in self:
                rec.selected_slot_display = (
                    f"{rec._float_to_ampm(rec.start_time)} – {rec._float_to_ampm(rec.end_time)}"
                )
            
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
    @api.constrains('start_time', 'end_time')
    def _check_booking_times(self):
        """Reject bookings that end before they start or run longer than 8 hours."""
        
        for rec in self:
            if not rec.start_time and not rec.end_time:
                continue
            if rec.end_time <= rec.start_time:
                raise ValidationError(_('End time must be after start time.'))
            if (rec.end_time - rec.start_time) > 8:
                raise ValidationError(_('Cannot book more than 8 hours.'))
            
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
        
    @api.constrains('meeting_room_id', 'start_time', 'end_time', 'state', 'booking_date')
    def _check_no_overlap(self):
        """Block confirming a booking that overlaps another confirmed booking of the same room."""
        
        for rec in self:
            if rec.state != 'confirmed' or not (rec.meeting_room_id and rec.booking_date and rec.end_time > rec.start_time):
                continue
            overlapping = self.search([
                ('id', '!=', rec.id),
                ('meeting_room_id', '=', rec.meeting_room_id.id),
                ('state', '=', 'confirmed'),
                ('booking_date', '=', rec.booking_date),
                ('start_time', '<', rec.end_time),
                ('end_time', '>', rec.start_time),
            ], limit=1)
            if overlapping:
                raise ValidationError(_(
                    "This room is already booked from %(start)s to %(end)s.",
                    start=self._float_to_ampm(overlapping.start_time),
                    end=self._float_to_ampm(overlapping.end_time),
                ))
                
    @api.onchange('meeting_room_id', 'start_time', 'end_time', 'booking_date')
    def _onchange_check_availability(self):
        """Warn in the UI when the chosen room and slot clash with a confirmed booking."""
        
        if self.meeting_room_id and self.booking_date and self.end_time > self.start_time:
            clash = self.search([
                ('id', '!=', self._origin.id),
                ('meeting_room_id', '=', self.meeting_room_id.id),
                ('state', '=', 'confirmed'),
                ('booking_date', '=', self.booking_date),
                ('start_time', '<', self.end_time),
                ('end_time', '>', self.start_time),
            ], limit=1)
            if clash:
                return {'warning': {
                    'title': _('Room Unavailable'),
                    'message': _('This room is booked for that slot. Please choose another time.'),
                }}
                
    @api.constrains('meeting_room_id', 'start_time', 'end_time')
    def _check_within_operating_hours(self):
        """Reject bookings that start before the room opens or end after it closes."""
        
        for rec in self:
            room = rec.meeting_room_id
            if not room or rec.end_time <= rec.start_time:
                continue
            if room.min_booking_hour and rec.start_time < room.min_booking_hour:
                raise ValidationError(_(
                    "Booking cannot start before the room opens at %s.",
                    rec._float_to_ampm(room.min_booking_hour),
                ))
            if room.max_booking_hour and rec.end_time > room.max_booking_hour:
                raise ValidationError(_(
                    "Booking cannot end after the room closes at %s.",
                    rec._float_to_ampm(room.max_booking_hour),
                ))

    @api.onchange('start_time', 'end_time')
    def _onchange_warn_outside_hours(self):
        """Warn in the UI when the picked times fall outside the room's operating window."""
        
        room = self.meeting_room_id
        if not room or self.end_time <= self.start_time:
            return
        if (room.min_booking_hour and self.start_time < room.min_booking_hour) or \
           (room.max_booking_hour and self.end_time > room.max_booking_hour):
            return {'warning': {
                'title': _('Outside Operating Hours'),
                'message': _(
                    "This room is open %(open)s–%(close)s. Please pick a time within that window.",
                    open=self._float_to_ampm(room.min_booking_hour),
                    close=self._float_to_ampm(room.max_booking_hour),
                ),
            }}
            
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
        """Cancel the booking, refunding any wallet hours it used and voiding its
        still-pending overage charge. Hours only come back if the wallet is still
        in the period they were drawn from."""

        self.ensure_one()
        if self.state == 'cancelled':
            raise UserError(_("This booking is already cancelled."))

        if self.state == 'confirmed':
            if self._is_in_past():
                raise UserError(_(
                    "%(booking)s started at %(start)s on %(date)s, so it can no "
                    "longer be cancelled.",
                    booking=self.name,
                    start=self._float_to_ampm(self.start_time),
                    date=format_date(self.env, self.booking_date),
                ))
            invoiced = self.contract_id.charge_ids.filtered(
                lambda c: c.booking_id == self and c.state == 'invoiced')
            if invoiced and not self.env.user.has_group(
                    'business_center.group_bc_manager'):
                raise UserError(_(
                    "The overage on %s is already on an invoice. Ask a manager "
                    "to cancel this booking.", self.name))
            posted = invoiced.filtered(
                lambda c: c.invoice_line_id.move_id.state == 'posted')
            if posted:
                raise UserError(_(
                    "The overage on %(booking)s is on posted invoice "
                    "%(invoice)s and cannot be cancelled. Issue a credit note "
                    "instead.",
                    booking=self.name,
                    invoice=posted[0].invoice_line_id.move_id.name,
                ))
            # Still-draft invoice: pull the line before voiding the charge.
            invoiced.invoice_line_id.unlink()
            invoiced.sudo().write({'state': 'cancelled', 'invoice_line_id': False})

            contract = self.contract_id
            if contract:
                self.env.cr.execute(
                    "SELECT id FROM business_center_contract WHERE id = %s FOR UPDATE",
                    (contract.id,))
                contract.invalidate_recordset(['wallet_balance'])

            wallet_used = self.wallet_balance_at_booking - self.wallet_balance_after_booking
            same_period = (
                contract
                and wallet_used > 0
                and self.wallet_period_date
                and contract.last_wallet_reset_date == self.wallet_period_date
            )
            if same_period:
                contract.wallet_balance = min(
                    contract.wallet_balance + wallet_used,
                    contract.free_hours_monthly,
                )
            elif wallet_used > 0:
                _logger.info(
                    "Booking %s cancelled after a wallet reset; %s hour(s) "
                    "lapsed with the previous period and were not refunded.",
                    self.name, wallet_used)

            charges = self.contract_id.charge_ids.filtered(
                lambda c: c.booking_id == self and c.state == 'pending')
            charges.sudo().write({'state': 'cancelled'})

        self.with_context(bc_state_from_action=True).write({'state': 'cancelled'})
        
    def action_reset_to_draft(self):
        """Reset to draft, reversing any wallet draw and overage charge first."""

        self.ensure_one()
        if not self.env.user.has_group('business_center.group_bc_manager'):
            raise UserError(_("Only a Business Center Manager can reset a booking."))
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
            'state': 'draft',
        })
                
    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
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

    def _booking_hours(self):
        """Return the booking duration in hours, or 0 if the times are invalid."""
        
        self.ensure_one()
        if self.end_time > self.start_time:
            return self.end_time - self.start_time
        return 0.0
    
    def _local_now(self):
        """Current date and time at the business centre. Booking dates and
        times are local to the building, so use the company's timezone, then
        the user's; portal users often have none set."""

        company = self[:1].company_id or self.env.company
        tz = company.partner_id.tz or self.env.user.tz or 'UTC'
        return fields.Datetime.context_timestamp(
            self.with_context(tz=tz), fields.Datetime.now())

    def _is_in_past(self):
        """True if the booking starts before now at the business centre."""

        self.ensure_one()
        now = self._local_now()
        today = now.date()
        if self.booking_date < today:
            return True
        return self.booking_date == today and \
            self.start_time < now.hour + now.minute / 60.0