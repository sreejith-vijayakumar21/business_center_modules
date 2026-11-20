# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError

# Fields a customer writes when asking to cancel; booking models that lock
# confirmed bookings let these through.
CANCEL_REQUEST_FIELDS = frozenset({
    'cancel_request_state', 'cancel_requested_at', 'cancel_requested_by_id', 'cancel_request_reason',
})
TODO_ACTIVITY = 'mail.mail_activity_data_todo'


class BusinessCenterCancelRequestMixin(models.AbstractModel):
    """Free cancellation until a cut-off before the start, and after it a
    customer's cancellation request that the centre's manager answers.

    Shared by every booking model (hot desks, meeting rooms, ...). A model
    using it says only what differs:

    * ``_bc_free_cancel_field``: the company field holding its cut-off in
      minutes before the start;
    * ``_bc_cancel_answer_template``: the XML id of its answer email;
    * ``_bc_cancel_answer_partners()``: who gets the answer.

    The model must also have ``mail.thread`` and ``mail.activity.mixin``, the
    slot fields (``booking_date``, ``start_time``), ``state``, ``name``,
    ``company_id``, ``center_id``, ``cancel_reason`` and ``cancelled_by_id``.
    The charge decision wizard answers the request through
    ``_bc_reject_cancel_request`` or the model's own ``_apply_cancellation``.
    """

    _name = 'business.center.cancel.request.mixin'
    _description = 'Business Center Cancellation Requests (shared rules)'

    _bc_free_cancel_field = None
    _bc_cancel_answer_template = None

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    cancel_request_state = fields.Selection([
        ('pending', 'Requested'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
    ], string='Cancellation Request', readonly=True, copy=False, tracking=True,
        help="The customer asked to cancel after free cancellation ended; the "
             "booking stays held until a manager answers.")
    cancel_requested_at = fields.Datetime(string='Requested At', readonly=True, copy=False)
    cancel_requested_by_id = fields.Many2one('res.users', string='Requested By', readonly=True, copy=False)
    cancel_request_reason = fields.Text(string="Customer's Reason", readonly=True, copy=False)

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_request_cancel(self, reason):
        """The customer asks to cancel once free cancellation has ended. The
        booking stays confirmed and held; the centre's manager decides with
        Decide Cancellation whether to cancel it (and charge) or keep it."""

        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("Please tell us why you want to cancel."))
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_("Only a confirmed booking can be cancelled."))
            if rec.cancel_request_state == 'pending':
                raise UserError(_("A cancellation of %s has already been requested.", rec.name))
        self.write({
            'cancel_request_state': 'pending',
            'cancel_requested_at': fields.Datetime.now(),
            'cancel_requested_by_id': self.env.uid,
            'cancel_request_reason': reason,
        })
        for rec in self:
            rec.message_post(body=Markup("<p><b>%s</b></p><p>%s</p>") % (
                _("The customer asked to cancel this booking."), reason))
            rec.activity_schedule(
                TODO_ACTIVITY,
                summary=_("Cancellation request"),
                note=_("%(booking)s: the customer asked to cancel (%(reason)s). Open it "
                       "and use Decide Cancellation to cancel it, with or without a "
                       "charge, or keep it.", booking=rec.name, reason=reason),
                user_id=(rec.center_id.manager_id or self.env.user).id,
            )

    def action_decide_cancel_request(self):
        """Open the charge decision wizard to answer the customer's request."""

        self.ensure_one()
        if self.cancel_request_state != 'pending' or self.state != 'confirmed':
            raise UserError(_("%s has no open cancellation request.", self.name))
        return self.action_open_cancel_wizard()

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _bc_cancel_request_fields(self):
        """Fields a customer may write on a confirmed booking to ask to cancel."""

        return CANCEL_REQUEST_FIELDS

    def _bc_minutes_to_start(self):
        """Minutes until the slot starts by the centre's clock (negative once
        started), counting whole days for bookings on other dates."""

        self.ensure_one()
        today, hour = (self.company_id or self.env.company)._bc_clock()
        days = (self.booking_date - today).days
        return (days * 24 + self.start_time - hour) * 60.0

    def _bc_free_cancel_policy_minutes(self):
        """The company's cut-off, in minutes before the start, for this kind of booking."""

        self.ensure_one()
        return (self.company_id or self.env.company)[self._bc_free_cancel_field]

    def _bc_free_cancel_minutes_left(self):
        """Minutes left to cancel for free. Zero or less means a request is needed."""

        self.ensure_one()
        return self._bc_minutes_to_start() - self._bc_free_cancel_policy_minutes()

    def _bc_can_cancel_free(self):
        """Whether the customer may still cancel without asking."""

        return self._bc_free_cancel_minutes_left() > 0

    def _bc_close_cancel_request(self, answer):
        """Close the pending requests among these bookings as ``answer``
        ('accepted', 'rejected' or 'withdrawn') and tick off the manager's
        to-do. Returns the bookings that had one."""

        pending = self.filtered(lambda b: b.cancel_request_state == 'pending')
        if pending:
            pending.write({'cancel_request_state': answer})
            label = dict(self._fields['cancel_request_state']._description_selection(self.env))[answer]
            pending.activity_feedback([TODO_ACTIVITY], feedback=_("Cancellation request: %s", label))
        return pending

    def _bc_reject_cancel_request(self, reason):
        """Keep the booking: the manager declined the customer's request."""

        self.ensure_one()
        if self.cancel_request_state != 'pending' or self.state != 'confirmed':
            raise UserError(_("%s has no open cancellation request.", self.name))
        self.write({'cancel_reason': reason, 'cancelled_by_id': self.env.uid})
        self._bc_close_cancel_request('rejected')
        self._bc_send_cancel_answer()

    def _bc_cancel_answer_partners(self):
        """Who is told the answer: whoever sent the request. Models add the
        person the booking is for."""

        self.ensure_one()
        return self.cancel_requested_by_id.partner_id

    def _bc_send_cancel_answer(self):
        """Send the answer to a cancellation request, posted in the chatter
        as a customer message so staff see what the customer was told."""

        template = self.env.ref(self._bc_cancel_answer_template, raise_if_not_found=False)
        if not template:
            return
        for rec in self:
            partners = rec._bc_cancel_answer_partners().filtered('email')
            if partners:
                rec.message_post_with_source(
                    template,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    partner_ids=partners.ids,
                )
