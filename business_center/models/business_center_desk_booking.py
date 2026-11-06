# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date

# Fields describing what was booked; fixed once the booking is confirmed.
LOCKED_AFTER_DRAFT = {
    'partner_id', 'contract_id', 'center_id', 'space_id', 'desk_id',
    'booking_date', 'start_time', 'end_time', 'hourly_rate',
}


class BusinessCenterDeskBooking(models.Model):
    """A hot desk booked by the hour, by anyone: a tenant (billed on their
    contract) or a walk-in (invoiced on its own). The slot rules come from
    the shared slot-booking mixin; this model adds the customer, the price,
    check-in, no-shows and billing."""

    _name = 'business.center.desk.booking'
    _description = 'Hot Desk Booking'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'business.center.slot.booking.mixin']
    _order = 'booking_date desc, start_time desc, id desc'

    # What the shared slot rules book: the hot desk, open per its coworking space.
    _slot_resource_field = 'desk_id'
    _slot_hours_path = 'space_id'
    _slot_blocking_states = ('confirmed', 'checked_in')

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    name = fields.Char(string='Booking', required=True, copy=False, readonly=True,
                       index='trigram', default=lambda self: _('New'))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('done', 'Done'),
        ('no_show', 'No-show'),
        ('released', 'Released'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    user_id = fields.Many2one('res.users', string='Booked By', default=lambda self: self.env.user,
                              copy=False)
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, tracking=True,
                                 help="Who uses the desk: a tenant's employee or a walk-in.")
    commercial_partner_id = fields.Many2one(related='partner_id.commercial_partner_id')
    contract_id = fields.Many2one(
        'business.center.contract', string='Bill to Contract', tracking=True,
        domain="[('state', '=', 'active'), ('partner_id', '=', commercial_partner_id)]",
        help="Bill this booking on the tenant's next monthly invoice. Leave empty "
             "to invoice it on its own.")
    center_id = fields.Many2one('business.center', string='Business Center', required=True)
    space_id = fields.Many2one('business.center.space', string='Coworking Space', required=True,
                               domain="[('center_id', '=', center_id), ('is_coworking', '=', True)]")
    desk_id = fields.Many2one(
        'business.center.desk', string='Hot Desk', required=True, tracking=True,
        domain="[('id', 'in', available_desk_ids), ('space_id', '=', space_id)]")
    available_desk_ids = fields.Many2many(
        'business.center.desk', string='Free Hot Desks', compute='_compute_available_desk_ids',
        help="Available hot desks (of the chosen centre, if any) not booked "
             "during this slot, for the dropdown and the floor picker.")
    hourly_rate = fields.Monetary(string='Hourly Rate', compute='_compute_hourly_rate',
                                  store=True, readonly=False, currency_field='currency_id')
    duration_display = fields.Char(string='Duration', compute='_compute_amount')
    amount = fields.Monetary(string='Amount', compute='_compute_amount', currency_field='currency_id')
    checked_in_at = fields.Datetime(string='Checked In At', readonly=True, copy=False)
    reminder_sent_at = fields.Datetime(string='Reminder Sent At', readonly=True, copy=False)
    customer_coming = fields.Boolean(
        string='Customer On the Way', readonly=True, copy=False, tracking=True,
        help="The customer answered the reminder: the desk is held until the "
             "end of the slot instead of being released early.")
    released_at = fields.Datetime(string='Released At', readonly=True, copy=False)
    billed_hours = fields.Float(string='Billed Hours', readonly=True, copy=False,
                                help="Hours charged: the slot when done, or the no-show or "
                                     "late release charge.")
    charge_id = fields.Many2one('business.center.contract.charge', string='Contract Charge',
                                readonly=True, copy=False)
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False)
    charge_to_decide = fields.Boolean(
        string='Charge to Decide', readonly=True, copy=False, tracking=True,
        help="Released or no-show without anyone deciding the charge yet; a "
             "manager settles it with Decide Charge.")
    cancel_outcome = fields.Selection([
        ('waive', 'Charges Waived'),
        ('used', 'Time Used Charged'),
        ('full', 'Charged in Full'),
    ], string='Charge Decision', readonly=True, copy=False, tracking=True)
    cancel_reason = fields.Text(string='Decision Reason', readonly=True, copy=False)
    cancelled_by_id = fields.Many2one('res.users', string='Decided By', readonly=True, copy=False)
    company_id = fields.Many2one(related='center_id.company_id', store=True, string='Company')
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')

    _no_double_booking = models.Constraint(
        """EXCLUDE USING gist (
               desk_id WITH =,
               booking_date WITH =,
               numrange(start_time::numeric, end_time::numeric) WITH &&
           ) WHERE (state IN ('confirmed', 'checked_in'))""",
        "This hot desk is already booked for part of that time slot.",
    )

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('desk_id')
    def _compute_hourly_rate(self):
        """Take the desk's hourly rate; stored so later rate changes do not
        reprice existing bookings."""

        for rec in self:
            rec.hourly_rate = rec.desk_id.hourly_rate

    @api.depends('start_time', 'end_time', 'hourly_rate')
    def _compute_amount(self):
        """Price of the booked slot: hours x hourly rate."""

        for rec in self:
            hours = rec._booking_hours()
            rec.duration_display = rec._float_to_duration(hours)
            rec.amount = rec.currency_id.round(hours * rec.hourly_rate) if rec.currency_id else 0.0

    @api.depends('center_id', 'booking_date', 'start_time', 'end_time')
    def _compute_available_desk_ids(self):
        """Available hot desks, of the centre when one is chosen, minus those
        held by another booking overlapping this slot."""

        Desk = self.env['business.center.desk']
        for rec in self:
            domain = [('desk_type', '=', 'hot'), ('state', '=', 'available'), ('is_bookable', '=', True)]
            if rec.center_id:
                domain.append(('center_id', '=', rec.center_id.id))
            desks = Desk.search(domain)
            if rec.booking_date and rec.end_time > rec.start_time:
                desks -= self.search([
                    ('desk_id', 'in', desks.ids),
                    ('state', 'in', self._slot_blocking_states),
                    ('booking_date', '=', rec.booking_date),
                    ('start_time', '<', rec.end_time),
                    ('end_time', '>', rec.start_time),
                    ('id', '!=', rec._origin.id or 0),
                ]).desk_id
            rec.available_desk_ids = desks

    @api.model_create_multi
    def create(self, vals_list):
        """Number new bookings (HD/2026/00001) and always start in Draft."""

        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft':
                raise UserError(_("A hot desk booking is created in Draft and confirmed with Confirm."))
            if vals.get('name', _("New")) == _("New"):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'business.center.desk.booking') or _("New")
        return super().create(vals_list)

    def write(self, vals):
        """What was booked, when and for whom is fixed once confirmed."""

        if LOCKED_AFTER_DRAFT & set(vals) and self.filtered(lambda b: b.state != 'draft'):
            raise UserError(_("Only a draft booking can be changed. Cancel it and book again."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        """Bookings are history; only drafts may be deleted."""

        if self.filtered(lambda b: b.state != 'draft'):
            raise UserError(_("Only draft bookings can be deleted. Cancel the booking instead."))

    def _slot_hours(self):
        """A coworking space without opening hours is open all day."""

        open_h, close_h = super()._slot_hours()
        return (open_h, close_h) if close_h else (0.0, 24.0)

    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------
    @api.onchange('center_id')
    def _onchange_center_id(self):
        """A different centre means a different coworking space and desk."""

        if self.space_id.center_id != self.center_id:
            self.space_id = False
            self.desk_id = False

    @api.onchange('space_id')
    def _onchange_space_id(self):
        """A different coworking space means a different desk."""

        if self.desk_id.space_id != self.space_id:
            self.desk_id = False

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Drop a contract that is not the new customer's company's."""

        if self.contract_id and self.contract_id.partner_id != self.commercial_partner_id:
            self.contract_id = False

    @api.onchange('desk_id')
    def _onchange_desk_slot(self):
        """A picked desk brings its coworking space and centre along, then
        the slot is re-checked against it."""

        if self.desk_id:
            self.space_id = self.desk_id.space_id
            self.center_id = self.desk_id.center_id
        return self._slot_onchange_warning()

    @api.constrains('desk_id')
    def _check_hot_desk(self):
        """Only hot desks are booked by the hour."""

        for rec in self:
            if rec.desk_id.desk_type != 'hot':
                raise ValidationError(_(
                    "%s is not a hot desk; dedicated desks are leased on contracts.",
                    rec.desk_id.display_name))

    @api.constrains('contract_id', 'partner_id', 'desk_id')
    def _check_contract(self):
        """A booking is billed to the customer's own contract, in the desk's centre."""

        for rec in self:
            contract = rec.contract_id
            if not contract:
                continue
            if contract.partner_id != rec.commercial_partner_id:
                raise ValidationError(_(
                    "Contract %(contract)s belongs to %(tenant)s, not to %(customer)s.",
                    contract=contract.name, tenant=contract.partner_id.display_name,
                    customer=rec.partner_id.display_name))
            if contract.center_id and contract.center_id != rec.desk_id.center_id:
                raise ValidationError(_(
                    "Contract %(contract)s is for %(center)s; book a hot desk there.",
                    contract=contract.name, center=contract.center_id.display_name))

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_confirm(self):
        """Hold the desk for the slot."""

        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only a draft booking can be confirmed."))
            if rec.desk_id.state != 'available':
                raise UserError(_("%s is not available for booking.", rec.desk_id.display_name))
            if not rec.desk_id.is_bookable:
                raise UserError(_("%s is withdrawn from booking.", rec.desk_id.display_name))
            if not rec._booking_hours():
                raise UserError(_("Pick a start and an end time first."))
            if rec.hourly_rate <= 0:
                raise UserError(_(
                    "%s has no hourly rate. Set the rate on the hot desk, or on "
                    "this booking for a special price.", rec.desk_id.display_name))
            if rec._is_in_past() and not self.env.user.has_group('business_center.group_bc_manager'):
                raise UserError(_(
                    "%s starts in the past. Ask a manager to record a past booking.", rec.name))
        self._slot_check_free()
        self.write({'state': 'confirmed'})

    def action_check_in(self):
        """The customer has arrived."""

        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_("Only a confirmed booking can be checked in."))
            if rec.booking_date != rec._local_now().date():
                raise UserError(_(
                    "%(booking)s is for %(date)s; check in on that day.",
                    booking=rec.name, date=format_date(self.env, rec.booking_date)))
        self.write({'state': 'checked_in', 'checked_in_at': fields.Datetime.now()})

    def action_done(self):
        """The customer has left: close the booking and bill the slot."""

        for rec in self:
            if rec.state != 'checked_in':
                raise UserError(_("Only a checked-in booking can be completed."))
            rec._bc_bill(rec._booking_hours())
        self.write({'state': 'done'})

    def action_cancel(self):
        """Cancel a booking. Before it starts this is free. Once it has
        started only a manager may cancel it, through the charge decision
        wizard, like a meeting room booking."""

        started = self.filtered(lambda b: b.state == 'confirmed' and b._is_in_past())
        for rec in self:
            if rec.state not in ('draft', 'confirmed'):
                raise UserError(_("Only a draft or confirmed booking can be cancelled."))
        if started:
            if not self.env.user.has_group('business_center.group_bc_manager'):
                raise UserError(_(
                    "%s has already started. Ask a manager to cancel it.", started[0].name))
            if len(self) > 1:
                raise UserError(_("Cancel started bookings one at a time."))
            return self.action_open_cancel_wizard()
        self.write({'state': 'cancelled'})

    def action_release(self):
        """Free the desk of a booking the customer will not use, said by the
        reminder link. Before the start it is a plain free cancellation;
        once started the desk is freed at once and a manager decides the
        charge."""

        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_("Only a confirmed booking that is not checked in can be released."))
        not_started = self.filtered(lambda b: not b._is_in_past())
        not_started.write({'state': 'cancelled'})
        started = self - not_started
        started.write({'state': 'released', 'released_at': fields.Datetime.now()})
        started._bc_request_charge_decision()

    def action_decide_charge(self):
        """Open the charge decision wizard for a released or no-show booking."""

        self.ensure_one()
        self._bc_check_settle()
        return self.action_open_cancel_wizard()

    def action_keep(self):
        """The customer is on the way: hold the desk until the end of the
        slot instead of releasing it early."""

        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_("Only a confirmed booking can be kept."))
        self.write({'customer_coming': True})

    def action_reset_to_draft(self):
        """Reopen a cancelled booking."""

        if self.filtered(lambda b: b.state != 'cancelled'):
            raise UserError(_("Only a cancelled booking can be reset to draft."))
        self.write({'state': 'draft'})

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _bc_mark_no_show(self):
        """Release the desk of a booking nobody checked in to; a manager
        decides the charge."""

        self.write({'state': 'no_show'})
        self._bc_request_charge_decision()

    def _bc_request_charge_decision(self):
        """Flag released and no-show bookings for a charge decision and ask
        the centre manager to make it."""

        self.write({'charge_to_decide': True})
        for rec in self:
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_("Decide hot desk charge"),
                note=_("%(booking)s ended as %(state)s. Open it and use Decide Charge "
                       "to waive it or charge the time used or the full slot.",
                       booking=rec.name,
                       state=dict(rec._fields['state']._description_selection(rec.env))[rec.state]),
                user_id=(rec.center_id.manager_id or rec.user_id or self.env.user).id,
            )

    def _bc_check_settle(self):
        """The charge decision wizard settles a started confirmed booking
        (cancelling it) or a released / no-show booking awaiting a decision."""

        self.ensure_one()
        if self.state == 'confirmed' or (self.state in ('released', 'no_show') and self.charge_to_decide):
            return
        if self.state in ('released', 'no_show'):
            raise UserError(_("The charge of %s has already been decided.", self.name))
        raise UserError(_("Only a confirmed, released or no-show booking can be settled here."))

    def _apply_cancellation(self, outcome=False, reason=False, used_until=False):
        """Settle the booking with the manager's decision: bill nothing, the
        time used, or the full slot. A confirmed booking is cancelled; a
        released or no-show one keeps its state."""

        self.ensure_one()
        if outcome == 'full':
            hours = self._booking_hours()
        elif outcome == 'used':
            hours = max(min(used_until or 0.0, self.end_time) - self.start_time, 0.0)
        else:
            hours = 0.0
        self._bc_bill(hours)
        vals = {
            'cancel_outcome': outcome or 'waive',
            'cancel_reason': reason,
            'cancelled_by_id': self.env.uid,
            'charge_to_decide': False,
        }
        if self.state == 'confirmed':
            vals['state'] = 'cancelled'
        self.write(vals)
        self.activity_feedback(['mail.mail_activity_data_todo'],
                               feedback=_("Charge decided: %s", dict(
                                   self._fields['cancel_outcome'].selection)[vals['cancel_outcome']]))

    def _bc_minutes_since_start(self, today, hour):
        """Minutes since the slot started (infinite for an earlier day)."""

        self.ensure_one()
        if self.booking_date < today:
            return float('inf')
        return (hour - self.start_time) * 60.0

    def _bc_reminder_template(self):
        """Mail template of the "still coming?" reminder. The portal module
        replaces it with one carrying Keep / Release buttons."""

        return self.env.ref('business_center.mail_template_hot_desk_reminder',
                            raise_if_not_found=False)

    def _bc_send_reminder(self):
        """Email the "still coming?" reminder once per booking."""

        for rec in self:
            template = rec._bc_reminder_template()
            if template and rec.partner_id.email:
                template.send_mail(rec.id)
                rec.message_post(body=_("Reminder sent: the booking has started and nobody has checked in."))
        self.write({'reminder_sent_at': fields.Datetime.now()})

    def _bc_customer_answer(self, answer):
        """Apply the customer's answer to the reminder and return what to
        tell them. ``answer`` is 'keep' or 'release'."""

        self.ensure_one()
        if self.state != 'confirmed':
            return _("This booking is %s, so there is nothing to change.",
                     dict(self._fields['state']._description_selection(self.env))[self.state])
        if answer == 'keep':
            self.action_keep()
            return _("Thank you, your desk is held until %s.", self._float_to_ampm(self.end_time))
        self.action_release()
        return _("Your desk has been released. Thank you for letting us know.")

    def _bc_bill(self, hours):
        """Bill ``hours`` of this booking: a pending charge on the contract,
        billed with its next monthly invoice, or an invoice of its own."""

        self.ensure_one()
        if hours <= 0:
            return
        self.billed_hours = hours
        if self.contract_id:
            self.charge_id = self.env['business.center.contract.charge'].sudo().create({
                'date': self.booking_date,
                'description': _("Hot desk %s", self.desk_id.name),
                'desk_booking_id': self.id,
                'contract_id': self.contract_id.id,
                'quantity': hours,
                'unit_price': self.hourly_rate,
            })
        else:
            self.invoice_id = self._bc_create_invoice(hours)

    def _bc_create_invoice(self, hours):
        """A customer invoice for a booking billed on its own. Posted and
        emailed when the company invoices automatically."""

        self.ensure_one()
        product = self.env.ref('business_center.product_hot_desk_booking', raise_if_not_found=False)
        if not product:
            raise UserError(_("The Hot Desk Booking product is missing, so %s could not be invoiced.",
                              self.name))
        move = self.env['account.move'].sudo().with_company(self.company_id).create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': fields.Date.context_today(self),
            'invoice_origin': self.name,
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'name': _("Hot Desk - %(desk)s, %(date)s %(slot)s (%(hours)s)",
                          desk=self.desk_id.name, date=format_date(self.env, self.booking_date),
                          slot=self.selected_slot_display, hours=self._float_to_duration(hours)),
                'quantity': 1.0,
                'price_unit': self.currency_id.round(hours * self.hourly_rate),
            })],
        })
        if self.company_id.bc_invoice_auto_send:
            move.action_post()
            template = self.env.ref('account.email_template_edi_invoice', raise_if_not_found=False)
            if template and self.partner_id.email:
                template.send_mail(move.id)
                move.is_move_sent = True
        return move

    # ------------------------------------------------------------------------------
    #   MARK: SCHEDULER METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _cron_process_hot_desk_bookings(self):
        """Run every few minutes, using each booking's company policy:
        remind customers who have not checked in, release unattended desks
        as no-shows (or at the end of the slot for customers on their way),
        and complete finished stays."""

        now = self._local_now()
        today, hour = now.date(), now.hour + now.minute / 60.0

        started = self.search([('state', '=', 'confirmed'), ('booking_date', '<=', today)])
        to_remind, no_shows = self.browse(), self.browse()
        for booking in started:
            company = booking.company_id
            minutes = booking._bc_minutes_since_start(today, hour)
            if minutes < 0:
                continue
            if booking.customer_coming:
                if booking.booking_date < today or booking.end_time <= hour:
                    no_shows |= booking
            elif minutes >= company.bc_hot_desk_checkin_grace:
                no_shows |= booking
            elif minutes >= company.bc_hot_desk_reminder_minutes and not booking.reminder_sent_at:
                to_remind |= booking
        to_remind._bc_send_reminder()
        no_shows._bc_mark_no_show()

        ended = self.search([('state', '=', 'checked_in'), ('booking_date', '<=', today)]).filtered(
            lambda b: b.booking_date < today or b.end_time <= hour)
        for booking in ended:
            booking.action_done()
