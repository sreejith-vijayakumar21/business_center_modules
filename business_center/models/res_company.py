# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import pytz

from odoo import _, api, fields, models

from odoo.exceptions import ValidationError 


class ResCompany(models.Model):
    _inherit = 'res.company'
    # Kind of unit -> company field holding its default photo, and the
    # built-in picture used when that field is empty.
    
    _BC_DEFAULT_PHOTO_FIELDS = {
        'coworking': 'bc_coworking_photo',
        'meeting_room': 'bc_meeting_room_photo',
    }
    _BC_BUILTIN_PHOTOS = {
        'coworking': '/business_center/static/img/bc_default_coworking.svg',
        'meeting_room': '/business_center/static/img/bc_default_meeting_room.svg',
    }

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
    bc_hot_desk_reminder_minutes = fields.Integer(
        string='Send Reminder After (min)', default=10,
        help="Minutes after a hot desk booking starts, without check-in, before "
             "the customer is asked whether they are still coming.")
    bc_hot_desk_checkin_grace = fields.Integer(
        string='Release Unattended Desk After (min)', default=30,
        help="Minutes after the start, without check-in or an answer, before "
             "the desk is released and the booking becomes a no-show.")
    bc_hot_desk_free_cancel_minutes = fields.Integer(
        string='Free Cancellation Until (min before start)', default=0,
        help="Customers cancel a hot desk booking for free until this many "
             "minutes before it starts. After that they send a cancellation "
             "request and a manager decides the charge. 0 keeps cancellation "
             "free right up to the start.")
    bc_meeting_room_free_cancel_minutes = fields.Integer(
        string='Meeting Room Free Cancellation Until (min before start)', default=0,
        help="Members cancel a meeting room booking for free until this many "
             "minutes before it starts. After that they send a cancellation "
             "request and a manager decides the charge. 0 keeps cancellation "
             "free right up to the start.")
    bc_coworking_photo = fields.Image(
        string='Default Coworking / Hot Desk Photo', max_width=1920, max_height=1920,
        help="Shown for coworking spaces, and the hot desks in them, that have "
             "no photo of their own. Leave empty to use the built-in picture.")
    bc_meeting_room_photo = fields.Image(
        string='Default Meeting Room Photo', max_width=1920, max_height=1920,
        help="Shown for meeting rooms that have no photo of their own. Leave "
             "empty to use the built-in picture.")
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
                
    @api.constrains('bc_hot_desk_free_cancel_minutes', 'bc_meeting_room_free_cancel_minutes')
    def _check_hot_desk_free_cancel(self):
        """The free cancellation cut-offs cannot be negative."""

        for company in self:
            if min(company.bc_hot_desk_free_cancel_minutes, company.bc_meeting_room_free_cancel_minutes) < 0:
                raise ValidationError(_("The free cancellation cut-off cannot be negative."))


    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _bc_tz(self):
        """Timezone of the business centre: the company's (Settings > Business
        Centre Timezone), then the user's, then UTC. Portal users and OdooBot
        often have none set, so the company's comes first."""

        company = self[:1] or self.env.company
        return company.partner_id.tz or self.env.user.tz or 'UTC'

    def _bc_now(self):
        """Current local date and time at the business centre (aware datetime)."""

        tz = pytz.timezone(self._bc_tz())
        return pytz.utc.localize(fields.Datetime.now()).astimezone(tz)

    def _bc_today(self):
        """Today's date at the business centre; fields.Date.today() is UTC and
        context_today() is the user's day."""

        return self._bc_now().date()
    
    def _bc_clock(self):
        """The centre's local date and hour as a float (10:30 -> 10.5), the
        way bookings store their times."""

        now = self._bc_now()
        return now.date(), now.hour + now.minute / 60.0
    
    def _bc_default_photo(self, kind):
        """Default photo for a unit of ``kind`` ('coworking' or
        'meeting_room'): ``(field, False)`` when this company has uploaded
        one, ``(False, url)`` for the built-in picture, ``(False, False)``
        for a kind without a default."""

        self.ensure_one()
        field = self._BC_DEFAULT_PHOTO_FIELDS.get(kind)
        if field and self[field]:
            return field, False
        return False, self._BC_BUILTIN_PHOTOS.get(kind, False)