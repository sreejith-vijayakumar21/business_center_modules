# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


def _resource_deps(*names):
    """Dependencies on the booked resource plus ``names``. The abstract
    mixin itself has no resource, so it depends on ``names`` only."""

    return lambda self: ((self._slot_resource_field,) if self._slot_resource_field else ()) + names


def _hours_deps(self):
    """Dependencies on the opening hours of the booked resource."""

    path = self._slot_hours_path
    return (f"{path}.min_booking_hour", f"{path}.max_booking_hour") if path else ()


class BusinessCenterSlotBookingMixin(models.AbstractModel):
    """Shared rules for booking a resource for a time slot on one day.

    A concrete booking model (meeting room, hot desk, ...) inherits this
    mixin and only says *what* is booked:

    * ``_slot_resource_field``: the many2one to the booked record;
    * ``_slot_hours_path``: path from the booking to the record holding the
      opening hours (``min_booking_hour`` / ``max_booking_hour``), e.g. the
      meeting room itself, or a hot desk's coworking space;
    * ``_slot_blocking_states``: booking states that hold the resource.

    Everything about the slot itself lives here once: date and times,
    opening hours, overlaps, the availability timeline, the 12-hour display
    and "has it started yet". The model must also have ``state``, ``name``
    and ``company_id``.
    """

    _name = 'business.center.slot.booking.mixin'
    _description = 'Business Center Slot Booking (shared rules)'
    _inherit = ['business.center.time.format.mixin']

    _slot_resource_field = None
    _slot_hours_path = None
    _slot_blocking_states = ('confirmed',)

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    booking_date = fields.Date(string='Date', required=True)
    start_time = fields.Float(string='Start Time')
    end_time = fields.Float(string='End Time')
    selected_slot_display = fields.Char(string='Selected Slot', store=True,
                                        compute='_compute_selected_slot_display')
    slot_open_hour = fields.Float(string='Opens', compute='_compute_slot_hours',
                                  help="Opening time of the booked resource.")
    slot_close_hour = fields.Float(string='Closes', compute='_compute_slot_hours',
                                   help="Closing time of the booked resource.")
    booked_ranges = fields.Json(string='Booked Slots', compute='_compute_booked_ranges',
                                help="[start, end] hours of the resource's other "
                                     "bookings that day, for the time pickers.")
    slot_availability_html = fields.Html(string='Slot Availability', sanitize=False,
                                         compute='_compute_slot_availability_html')

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('start_time', 'end_time')
    def _compute_selected_slot_display(self):
        """The selected slot in 12-hour notation, e.g. '9:00 AM – 10:30 AM'."""

        for rec in self:
            rec.selected_slot_display = (
                f"{rec._float_to_ampm(rec.start_time)} – {rec._float_to_ampm(rec.end_time)}"
            )

    @api.depends(_hours_deps)
    def _compute_slot_hours(self):
        """Opening and closing time of the booked resource."""

        for rec in self:
            holder = rec._slot_hours_holder()
            rec.slot_open_hour = holder.min_booking_hour if holder else 0.0
            rec.slot_close_hour = holder.max_booking_hour if holder else 0.0

    @api.depends(_resource_deps('booking_date'))
    def _compute_booked_ranges(self):
        """The resource's other bookings that day as [start, end] hour pairs,
        so the time pickers can grey out times already taken."""

        for rec in self:
            rec.booked_ranges = [[b.start_time, b.end_time] for b in rec._slot_other_bookings()]

    @api.depends(_resource_deps('booking_date'))
    def _compute_slot_availability_html(self):
        """Render the day's timeline as coloured slot boxes, splitting the
        opening hours at every booking edge and marking each part busy or free."""

        for rec in self:
            holder = rec._slot_hours_holder()
            if not rec._slot_resource() or not rec.booking_date or not holder.max_booking_hour:
                rec.slot_availability_html = False
                continue

            open_h = holder.min_booking_hour or 0.0
            close_h = holder.max_booking_hour
            existing = rec._slot_other_bookings()

            # 1. Boundary points: the day's edges plus every booking edge,
            #    clamped to opening hours and de-duplicated.
            points = {open_h, close_h}
            for b in existing:
                if open_h < b.start_time < close_h:
                    points.add(b.start_time)
                if open_h < b.end_time < close_h:
                    points.add(b.end_time)
            points = sorted(points)

            # 2. Each consecutive pair is one segment, coloured by whether a
            #    booking covers its midpoint.
            boxes = []
            for seg_start, seg_end in zip(points, points[1:]):
                if seg_end - seg_start < 0.001:
                    continue
                mid = (seg_start + seg_end) / 2.0
                booked = existing.filtered(lambda b: b.start_time <= mid < b.end_time)
                occupied = bool(booked)
                color = '#e74c8b' if occupied else '#7ed957'
                # Staff see the booking reference; portal users only see that
                # the slot is taken, not another customer's booking number.
                if not occupied:
                    title = _('Available')
                elif self.env.user.share:
                    title = _('Booked')
                else:
                    title = booked[:1].name
                label = "%s – %s" % (rec._float_to_ampm(seg_start), rec._float_to_ampm(seg_end))
                boxes.append(
                    "<div class='o_bc_slot %s' data-start='%s' data-end='%s' "
                    "title='%s' style='background:%s;color:#111;"
                    "padding:5px 8px;border-radius:5px;font-size:11px;"
                    "text-align:center;white-space:nowrap;'>%s</div>"
                    % ('o_bc_slot_busy' if occupied else 'o_bc_slot_free',
                       seg_start, seg_end, escape(title), color, label)
                )
            rec.slot_availability_html = (
                "<div style='display:flex;flex-wrap:wrap;gap:6px;'>%s</div>" % "".join(boxes)
            )

    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------
    @api.constrains('start_time', 'end_time')
    def _check_booking_times(self):
        """Reject bookings that end before they start. How long a booking may
        run is bounded by the opening hours, not by a fixed limit."""

        for rec in self:
            if not rec.start_time and not rec.end_time:
                continue
            if rec.end_time <= rec.start_time:
                raise ValidationError(_('End time must be after start time.'))

    @api.constrains(_resource_deps('start_time', 'end_time', 'state', 'booking_date'))
    def _check_no_overlap(self):
        """Refuse a holding booking that overlaps another holding booking of
        the same resource."""

        for rec in self:
            if rec.state not in rec._slot_blocking_states or rec.end_time <= rec.start_time:
                continue
            overlapping = rec._slot_overlapping()
            if overlapping:
                raise ValidationError(_(
                    "%(resource)s is already booked from %(start)s to %(end)s.",
                    resource=rec._slot_resource().display_name,
                    start=self._float_to_ampm(overlapping.start_time),
                    end=self._float_to_ampm(overlapping.end_time),
                ))

    @api.constrains(_resource_deps('start_time', 'end_time'))
    def _check_within_operating_hours(self):
        """Reject bookings that start before the resource opens or end after
        it closes."""

        for rec in self:
            holder = rec._slot_hours_holder()
            if not holder or rec.end_time <= rec.start_time:
                continue
            if holder.min_booking_hour and rec.start_time < holder.min_booking_hour:
                raise ValidationError(_(
                    "Booking cannot start before %(resource)s opens at %(time)s.",
                    resource=rec._slot_resource().display_name,
                    time=rec._float_to_ampm(holder.min_booking_hour),
                ))
            if holder.max_booking_hour and rec.end_time > holder.max_booking_hour:
                raise ValidationError(_(
                    "Booking cannot end after %(resource)s closes at %(time)s.",
                    resource=rec._slot_resource().display_name,
                    time=rec._float_to_ampm(holder.max_booking_hour),
                ))

    @api.onchange('start_time', 'end_time', 'booking_date')
    def _onchange_slot(self):
        """Warn in the form when the slot clashes or falls outside opening
        hours. Concrete models also call it when their resource changes."""

        return self._slot_onchange_warning()

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _slot_resource(self):
        """The booked record."""

        return self[self._slot_resource_field]

    def _slot_hours_holder(self):
        """The record holding the opening hours of the booked resource."""

        return self.mapped(self._slot_hours_path)[:1]

    def _slot_other_bookings(self):
        """Other holding bookings of the same resource on the same day."""

        self.ensure_one()
        resource = self._slot_resource()
        if not (resource and self.booking_date):
            return self.browse()
        domain = [
            (self._slot_resource_field, '=', resource.id),
            ('state', 'in', self._slot_blocking_states),
            ('booking_date', '=', self.booking_date),
        ]
        if self._origin.id:
            domain.append(('id', '!=', self._origin.id))
        return self.search(domain)

    def _slot_overlapping(self):
        """The first other holding booking overlapping this slot, if any."""

        self.ensure_one()
        return self._slot_other_bookings().filtered(
            lambda b: b.start_time < self.end_time and b.end_time > self.start_time)[:1]

    def _slot_onchange_warning(self):
        """Form warning for a clashing slot or one outside opening hours."""

        if not (self._slot_resource() and self.booking_date and self.end_time > self.start_time):
            return None
        if self._slot_overlapping():
            return {'warning': {
                'title': _('Unavailable'),
                'message': _('This slot is already booked. Please choose another time.'),
            }}
        holder = self._slot_hours_holder()
        if (holder.min_booking_hour and self.start_time < holder.min_booking_hour) or \
           (holder.max_booking_hour and self.end_time > holder.max_booking_hour):
            return {'warning': {
                'title': _('Outside Opening Hours'),
                'message': _(
                    "Open %(open)s–%(close)s. Please pick a time within that window.",
                    open=self._float_to_ampm(holder.min_booking_hour),
                    close=self._float_to_ampm(holder.max_booking_hour),
                ),
            }}
        return None

    def _booking_hours(self):
        """The booking duration in hours, or 0 if the times are invalid."""

        self.ensure_one()
        if self.end_time > self.start_time:
            return self.end_time - self.start_time
        return 0.0

    def _local_now(self):
        """Current date and time at the business centre: the company's
        timezone, then the user's; portal users often have none set."""

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
