# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import plaintext2html
from odoo.tools.mimetypes import guess_mimetype

# States in which the ticket still needs work.
OPEN_STATES = ('new', 'in_progress', 'waiting')
# States in which the clock runs: waiting on the member does not count.
CLOCK_STATES = ('new', 'in_progress')
# Company field holding the response target (hours) of each priority.
TARGET_FIELDS = {
    '0': 'bc_ticket_hours_low',
    '1': 'bc_ticket_hours_normal',
    '2': 'bc_ticket_hours_high',
    '3': 'bc_ticket_hours_urgent',
}
TODO_ACTIVITY = 'business_center_ticket.mail_activity_type_ticket'
MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 5 * 1024 * 1024
IMAGE_MIMETYPES = ('image/png', 'image/jpeg', 'image/gif', 'image/webp')


class BusinessCenterTicket(models.Model):
    """An internet, facilities or maintenance problem reported by a member
    (or by staff on their behalf), assigned to a staff member and followed
    until it is resolved.

    The ticket owns its own rules: who it is assigned to, its response
    target, which steps are allowed and who is told. Controllers and views
    only call these methods.
    """

    _name = 'business.center.ticket'
    _description = 'Support Ticket'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, id desc'
    _rec_names_search = ['name', 'subject']

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    name = fields.Char(string='Ticket', required=True, copy=False, readonly=True,
                       index='trigram', default=lambda self: _('New'))
    subject = fields.Char(string='Subject', required=True, tracking=True)
    description = fields.Text(string='Description', required=True)
    state = fields.Selection([
        ('new', 'Open'),
        ('in_progress', 'In Progress'),
        ('waiting', 'Waiting on Member'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='new', required=True, tracking=True, copy=False, group_expand=True)
    category_id = fields.Many2one('business.center.ticket.category', string='Category',
                                  required=True, tracking=True, ondelete='restrict')
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent'),
    ], string='Priority', default='1', required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Reported By', required=True, tracking=True,
                                 help="The member who has the problem.")
    commercial_partner_id = fields.Many2one(related='partner_id.commercial_partner_id',
                                            string='Tenant', store=True, index=True)
    contract_id = fields.Many2one(
        'business.center.contract', string='Contract',
        domain="[('partner_id', '=', commercial_partner_id), ('state', '=', 'active')]")
    center_id = fields.Many2one('business.center', string='Business Center', required=True, tracking=True)
    space_id = fields.Many2one('business.center.space', string='Space',
                               domain="[('center_id', '=', center_id)]")
    desk_id = fields.Many2one('business.center.desk', string='Desk',
                              domain="[('center_id', '=', center_id)]")
    unit_display = fields.Char(string='Where', compute='_compute_unit_display')
    user_id = fields.Many2one('res.users', string='Assigned To', tracking=True, copy=False,
                              domain="[('share', '=', False)]")
    photo_ids = fields.Many2many('ir.attachment', 'business_center_ticket_photo_rel',
                                 'ticket_id', 'attachment_id', string='Photos', copy=False)
    deadline = fields.Datetime(string='Resolve Before', readonly=True, copy=False,
                               help="Creation (or reopening) time plus the company's target for the priority.")
    is_overdue = fields.Boolean(string='Overdue', compute='_compute_is_overdue', search='_search_is_overdue')
    overdue_notified = fields.Boolean(readonly=True, copy=False)
    started_at = fields.Datetime(string='Started At', readonly=True, copy=False)
    resolved_at = fields.Datetime(string='Resolved At', readonly=True, copy=False)
    closed_at = fields.Datetime(string='Closed At', readonly=True, copy=False)
    resolution = fields.Text(string='Resolution', copy=False,
                             help="What was done. Sent to the member when the ticket is resolved.")
    resolution_hours = fields.Float(string='Time to Resolve', readonly=True, copy=False, aggregator='avg')
    reopen_count = fields.Integer(string='Times Reopened', readonly=True, copy=False)
    company_id = fields.Many2one(related='center_id.company_id', store=True, string='Company')

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('name', 'subject')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s - %s' % (rec.name, rec.subject) if rec.subject else rec.name

    @api.depends('space_id', 'desk_id')
    def _compute_unit_display(self):
        """The desk, else the space, else the centre in general."""

        for rec in self:
            rec.unit_display = rec.desk_id.name or rec.space_id.name or _("General / common area")

    @api.depends('deadline', 'state')
    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_overdue = bool(rec.deadline) and rec.state in CLOCK_STATES and rec.deadline < now

    def _search_is_overdue(self, operator, value):
        if operator in ('=', '!='):
            overdue = (operator == '=') == bool(value)
        elif operator in ('in', 'not in'):
            overdue = (operator == 'in') == any(value)
        else:
            return NotImplemented
        now = fields.Datetime.now()
        if overdue:
            return [('deadline', '<', now), ('state', 'in', CLOCK_STATES)]
        return ['|', '|', ('deadline', '=', False), ('deadline', '>=', now),
                ('state', 'not in', CLOCK_STATES)]

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = '/my/tickets/%s' % rec.id

    @api.model_create_multi
    def create(self, vals_list):
        """Number the ticket (TK/2026/00001), assign it, set its target, let
        the member follow it and give the assignee a to-do."""

        for vals in vals_list:
            if vals.get('name', _("New")) == _("New"):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'business.center.ticket') or _("New")
        tickets = super().create(vals_list)
        for ticket in tickets.filtered(lambda t: not t.user_id):
            ticket.user_id = ticket.category_id._bc_assignee_for(ticket.center_id)
        tickets._bc_set_deadline()
        for ticket in tickets:
            ticket.message_subscribe(partner_ids=ticket.partner_id.ids)
        tickets._bc_sync_todo()
        return tickets

    def write(self, vals):
        """A new priority means a new target; a new assignee takes over the to-do."""

        res = super().write(vals)
        if 'priority' in vals:
            self._bc_set_deadline()
        if 'user_id' in vals:
            self._bc_sync_todo()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_handled(self):
        """Tickets are history; only cancelled ones may be deleted."""

        if self.filtered(lambda t: t.state != 'cancelled'):
            raise UserError(_("Only cancelled tickets can be deleted. Cancel the ticket instead."))

    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------
    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Drop a contract that is not the member's company's."""

        if self.contract_id and self.contract_id.partner_id != self.commercial_partner_id:
            self.contract_id = False

    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        """A contract brings its centre along."""

        if self.contract_id.center_id:
            self.center_id = self.contract_id.center_id

    @api.onchange('center_id')
    def _onchange_center_id(self):
        """A different centre means a different space and desk."""

        if self.space_id.center_id != self.center_id:
            self.space_id = False
            self.desk_id = False

    @api.onchange('desk_id')
    def _onchange_desk_id(self):
        """A desk brings its space and centre along."""

        if self.desk_id:
            self.space_id = self.desk_id.space_id
            self.center_id = self.desk_id.space_id.center_id

    @api.onchange('space_id')
    def _onchange_space_id(self):
        """A space brings its centre along and drops a desk of another space."""

        if self.space_id:
            self.center_id = self.space_id.center_id
        if self.desk_id and self.desk_id.space_id != self.space_id:
            self.desk_id = False

    @api.constrains('partner_id', 'contract_id', 'center_id', 'space_id', 'desk_id')
    def _check_scope(self):
        """The contract is the member's company's, and the contract, space
        and desk all belong to the ticket's centre."""

        for rec in self:
            contract = rec.contract_id
            if contract and contract.partner_id != rec.commercial_partner_id:
                raise ValidationError(_(
                    "Contract %(contract)s belongs to %(tenant)s, not to %(member)s.",
                    contract=contract.name, tenant=contract.partner_id.display_name,
                    member=rec.partner_id.display_name))
            if contract.center_id and contract.center_id != rec.center_id:
                raise ValidationError(_(
                    "Contract %(contract)s is for %(center)s.",
                    contract=contract.name, center=contract.center_id.display_name))
            if rec.space_id and rec.space_id.center_id != rec.center_id:
                raise ValidationError(_(
                    "%(space)s is not in %(center)s.",
                    space=rec.space_id.display_name, center=rec.center_id.display_name))
            if rec.desk_id and rec.desk_id.space_id.center_id != rec.center_id:
                raise ValidationError(_(
                    "%(desk)s is not in %(center)s.",
                    desk=rec.desk_id.display_name, center=rec.center_id.display_name))

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_start(self):
        """Staff begin working on the ticket (or resume after the member answered)."""

        for rec in self:
            if rec.state not in ('new', 'waiting'):
                raise UserError(_("Only an open or waiting ticket can be started."))
        for rec in self:
            rec.write({'state': 'in_progress', 'started_at': rec.started_at or fields.Datetime.now()})

    def action_wait_member(self):
        """Staff need something from the member; the response clock stops."""

        for rec in self:
            if rec.state not in ('new', 'in_progress'):
                raise UserError(_("Only an open ticket can wait on the member."))
        self.write({'state': 'waiting'})

    def action_resolve(self):
        """The problem is fixed: record how long it took, close the to-do and
        tell the member what was done."""

        for rec in self:
            if rec.state not in OPEN_STATES:
                raise UserError(_("Only an open ticket can be resolved."))
            if not (rec.resolution or '').strip():
                raise UserError(_(
                    "Write what was done under Resolution first; it is sent to the member."))
        now = fields.Datetime.now()
        for rec in self:
            rec.write({
                'state': 'resolved',
                'resolved_at': now,
                'started_at': rec.started_at or now,
                'resolution_hours': (now - rec.create_date).total_seconds() / 3600.0,
            })
        self.activity_feedback([TODO_ACTIVITY], feedback=_("Resolved"))
        self._bc_notify_resolved()

    def action_close(self):
        """Nothing more to do on a resolved ticket; it can no longer be reopened by the member."""

        for rec in self:
            if rec.state != 'resolved':
                raise UserError(_("Only a resolved ticket can be closed."))
        self.write({'state': 'closed', 'closed_at': fields.Datetime.now()})

    def action_reopen(self):
        """The problem is back: work resumes with a fresh response target."""

        for rec in self:
            if rec.state not in ('resolved', 'closed'):
                raise UserError(_("Only a resolved or closed ticket can be reopened."))
        for rec in self:
            rec.write({
                'state': 'in_progress',
                'resolved_at': False,
                'closed_at': False,
                'resolution_hours': 0.0,
                'reopen_count': rec.reopen_count + 1,
            })
        self._bc_set_deadline(since=fields.Datetime.now())
        self._bc_sync_todo()

    def action_cancel(self):
        """The ticket was raised by mistake or is no longer needed."""

        for rec in self:
            if rec.state not in OPEN_STATES:
                raise UserError(_("Only an open ticket can be cancelled."))
        self.write({'state': 'cancelled'})
        self.activity_unlink([TODO_ACTIVITY])

    def action_take_out_of_service(self):
        """Open the out-of-service wizard of the desk or space this ticket is
        about. Nothing leaves service by itself; the manager decides."""

        self.ensure_one()
        unit = self.desk_id or self.space_id
        if not unit:
            raise UserError(_("This ticket is not about a particular space or desk."))
        return unit.with_context(bc_target_state='maintenance').action_open_out_of_service_wizard()

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    def _bc_set_deadline(self, since=None):
        """Response target: ``since`` (default: creation) plus the company's
        hours for the ticket's priority."""

        for rec in self:
            policy = rec.company_id or self.env.company
            start = since or rec.create_date or fields.Datetime.now()
            rec.write({
                'deadline': start + timedelta(hours=policy[TARGET_FIELDS[rec.priority]]),
                'overdue_notified': False,
            })

    def _bc_sync_todo(self):
        """Exactly one to-do, for the current assignee, while the ticket is open."""

        self.activity_unlink([TODO_ACTIVITY])
        for rec in self.filtered(lambda t: t.state in OPEN_STATES and t.user_id):
            rec.activity_schedule(
                TODO_ACTIVITY,
                date_deadline=fields.Date.to_date(rec.deadline) if rec.deadline else None,
                summary=_("Handle ticket: %s", rec.subject),
                note=_("%(member)s (%(tenant)s) reported: %(subject)s",
                       member=rec.partner_id.name, tenant=rec.commercial_partner_id.name,
                       subject=rec.subject),
                user_id=rec.user_id.id,
            )

    def _bc_notify_resolved(self):
        """Tell the member the ticket is resolved, with what was done. Posted
        as a customer message, so it shows in the chatter and on the portal."""

        template = self.env.ref('business_center_ticket.mail_template_ticket_resolved',
                                raise_if_not_found=False)
        if not template:
            return
        for rec in self:
            rec.message_post_with_source(
                template,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                partner_ids=rec.partner_id.ids,
            )

    def _bc_flag_overdue(self):
        """Note that the target was missed and escalate to the centre's manager."""

        for rec in self:
            rec.message_post(body=_("This ticket is past its response target."))
            manager = rec.center_id.manager_id
            if manager and manager != rec.user_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_warning',
                    summary=_("Overdue ticket: %s", rec.subject),
                    note=_("%(ticket)s, assigned to %(user)s, is past its response target.",
                           ticket=rec.name, user=rec.user_id.name or _("nobody")),
                    user_id=manager.id,
                )
        self.write({'overdue_notified': True})

    def _bc_can_reopen(self):
        """Whether the member may still reopen this resolved ticket."""

        self.ensure_one()
        days = (self.company_id or self.env.company).bc_ticket_reopen_days
        return bool(self.state == 'resolved' and days and self.resolved_at
                    and self.resolved_at >= fields.Datetime.now() - timedelta(days=days))

    def _bc_check_images(self, images):
        """Check uploaded photos: how many, how big, and that they really
        are images.

        :param images: [(filename, bytes)], as read from the upload
        :return: [(filename, bytes, mimetype)] of the non-empty ones
        """

        images = [(name, content) for name, content in images if content]
        if len(images) > MAX_PHOTOS:
            raise UserError(_("Please attach at most %s photos.", MAX_PHOTOS))
        checked = []
        for name, content in images:
            if len(content) > MAX_PHOTO_BYTES:
                raise UserError(_("%s is larger than 5 MB.", name))
            mimetype = guess_mimetype(content)
            if mimetype not in IMAGE_MIMETYPES:
                raise UserError(_("%s is not a photo (PNG, JPEG, GIF or WebP).", name))
            checked.append((name, content, mimetype))
        return checked

    def _bc_create_images(self, images):
        """Store checked photos as attachments of this ticket.

        :param images: [(filename, bytes)]
        :return: the created ir.attachment records
        """

        self.ensure_one()
        return self.env['ir.attachment'].sudo().create([{
            'name': name,
            'raw': content,
            'mimetype': mimetype,
            'res_model': self._name,
            'res_id': self.id,
        } for name, content, mimetype in self._bc_check_images(images)])

    def _bc_add_photos(self, images):
        """Attach the photos sent with a new ticket."""

        self.ensure_one()
        attachments = self._bc_create_images(images)
        if attachments:
            self.photo_ids = [(4, attachment.id) for attachment in attachments]

    def _bc_customer_reply(self, partner, body, images=()):
        """The member writes on the ticket; a ticket waiting on them goes
        back to work."""

        self.ensure_one()
        body = (body or '').strip()
        if not body:
            raise UserError(_("Please write a message."))
        if self.state in ('closed', 'cancelled'):
            raise UserError(_("%s is closed. Please raise a new ticket.", self.name))
        photos = self._bc_check_images(images)
        self.message_post(
            body=plaintext2html(body),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            author_id=partner.id,
            # Given as content, not ids: for a portal author Odoo only links
            # attachments it creates itself while posting.
            attachments=[(name, content) for name, content, _mimetype in photos],
        )
        if self.state == 'waiting':
            self.write({'state': 'in_progress'})

    def _bc_customer_reopen(self, partner, reason):
        """The member says the problem is not solved, inside the reopen window."""

        self.ensure_one()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("Please tell us what is still wrong."))
        if not self._bc_can_reopen():
            raise UserError(_("%s can no longer be reopened. Please raise a new ticket.", self.name))
        self.action_reopen()
        self.message_post(
            body=plaintext2html(_("Reopened: %s", reason)),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            author_id=partner.id,
        )

    def _bc_portal_messages(self):
        """The conversation the member may see: customer messages only, never
        internal notes or field tracking; oldest first."""

        self.ensure_one()
        return self.message_ids.filtered(
            lambda m: m.message_type in ('comment', 'email', 'email_outgoing')
            and m.subtype_id and not m.subtype_id.internal and not m.is_internal
        ).sorted('id')

    def _bc_portal_attachments(self):
        """Attachments the member may open: the ticket's photos and those on
        the visible conversation."""

        self.ensure_one()
        return self.photo_ids | self._bc_portal_messages().attachment_ids

    # ------------------------------------------------------------------------------
    #   MARK: SCHEDULER METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _cron_process_tickets(self):
        """Run hourly: flag tickets past their response target once, and
        close resolved tickets whose reopen window is over."""

        now = fields.Datetime.now()
        self.search([
            ('state', 'in', CLOCK_STATES),
            ('deadline', '<', now),
            ('overdue_notified', '=', False),
        ])._bc_flag_overdue()

        resolved = self.search([('state', '=', 'resolved')])
        resolved.filtered(lambda t: not t._bc_can_reopen()).action_close()
