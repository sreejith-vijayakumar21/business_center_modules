# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext, plaintext2html
from odoo.tools.mimetypes import guess_mimetype

# Members share one kind of post: text, photos or both. Announcements are
# the business centre's.
MEMBER_POST_TYPE = 'update'
REVIEW_ACTIVITY = 'business_center_community.mail_activity_type_post_review'
TENANT_GROUP = 'business_center_portal.group_bc_tenant_employee'
MAX_PHOTOS = 6
MAX_PHOTO_BYTES = 5 * 1024 * 1024
IMAGE_MIMETYPES = ('image/png', 'image/jpeg', 'image/gif', 'image/webp')
SUMMARY_LENGTH = 220
# Who sees a post. Members may keep one to their own company; staff posts
# always reach the whole centre.
AUDIENCES = [
    ('center', 'Everyone at the Centre'),
    ('company', 'Only My Company'),
]


class BusinessCenterPost(models.Model):
    """A post on the community feed: an announcement or update from the
    business centre, or an update or photos shared by a member.

    The post owns its own rules: who may see it, who may post what, when a
    member's post needs approval and who is told. Controllers and views only
    call these methods.
    """

    _name = 'business.center.post'
    _description = 'Community Post'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'is_pinned desc, published_at desc, id desc'

    # ------------------------------------------------------------------------------
    #   MARK: FIELDS
    # ------------------------------------------------------------------------------
    name = fields.Char(string='Title', required=True, tracking=True)
    post_type = fields.Selection([
        ('announcement', 'Announcement'),
        ('update', 'Post'),
    ], string='Type', default='announcement', required=True, tracking=True,
        help="Announcement: an official notice from the business centre, which "
             "can be emailed as Important. Post: an ordinary update, with text, "
             "photos or both.")
    body = fields.Html(string='Text', sanitize=True)
    summary = fields.Char(string='Summary', compute='_compute_summary')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Awaiting Approval'),
        ('published', 'Published'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)
    active = fields.Boolean(default=True)
    author_id = fields.Many2one(
        'res.partner', string='Author', required=True,
        default=lambda self: self.env.user.partner_id,
        domain="[('user_ids.share', '=', False)]",
        help="Who wrote the post. A member's post is authored by the member; "
             "a post created here by staff must be authored by an internal user.")
    author_company_id = fields.Many2one(related='author_id.commercial_partner_id',
                                        string="Author's Company", store=True)
    is_member_post = fields.Boolean(string='Posted by a Member', readonly=True, copy=False)
    center_id = fields.Many2one('business.center', string='Business Center', tracking=True,
                                help="Members of this centre see the post. Leave empty for all centres.")
    audience = fields.Selection(AUDIENCES, string='Visible To', default='center', required=True, tracking=True,
        help="Everyone at the centre, or only the members of the author's own "
             "company. Only a member's post can be kept to their company.")
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)
    is_pinned = fields.Boolean(string='Pinned', tracking=True,
                               help="Pinned posts stay at the top of the feed.")
    is_important = fields.Boolean(
        string='Important', tracking=True,
        help="An important announcement is also emailed to the members it concerns when published.")
    important_sent = fields.Boolean(readonly=True, copy=False)
    allow_comments = fields.Boolean(string='Allow Comments', default=True)
    expires_on = fields.Date(string='Show Until',
                             help="The post leaves the feed after this date. Leave empty to keep it.")
    published_at = fields.Datetime(string='Published At', readonly=True, copy=False)
    moderated_by_id = fields.Many2one('res.users', string='Approved / Rejected By',
                                      readonly=True, copy=False)
    reject_reason = fields.Text(string='Rejection Reason', copy=False,
                                help="Sent to the member when their post is rejected.")
    photo_ids = fields.Many2many('ir.attachment', 'business_center_post_photo_rel',
                                 'post_id', 'attachment_id', string='Photos', copy=False)
    comment_count = fields.Integer(string='Comments', compute='_compute_comment_count')

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    @api.depends('body')
    def _compute_summary(self):
        """The first lines of the text, for the feed cards."""

        for rec in self:
            text = ' '.join(html2plaintext(rec.body or '').split())
            rec.summary = text if len(text) <= SUMMARY_LENGTH else text[:SUMMARY_LENGTH].rstrip() + '…'

    def _compute_comment_count(self):
        for rec in self:
            rec.comment_count = len(rec._bc_portal_messages())

    def _compute_access_url(self):
        super()._compute_access_url()
        for rec in self:
            rec.access_url = '/my/community/%s' % rec.id

    # ------------------------------------------------------------------------------
    #   MARK: CONSTRAINT/ONCHANGE METHODS
    # ------------------------------------------------------------------------------
    @api.onchange('center_id')
    def _onchange_center_id(self):
        """A post for one centre belongs to that centre's company."""

        if self.center_id.company_id:
            self.company_id = self.center_id.company_id

    @api.onchange('post_type')
    def _onchange_post_type(self):
        """Only announcements are emailed as important."""

        if self.post_type != 'announcement':
            self.is_important = False
            
    @api.constrains('audience', 'is_member_post')
    def _check_audience(self):
        """Only a member's post can be kept to their company; a staff post
        has no author company to keep it to."""

        for rec in self:
            if rec.audience == 'company' and not rec.is_member_post:
                raise UserError(_(
                    "%s is a business centre post, so it is visible to everyone at "
                    "the centre. Only members can keep a post to their own company.",
                    rec.name))
                
    @api.constrains('author_id', 'is_member_post')
    def _check_staff_author(self):
        """A business centre post speaks for the centre, so its author is
        one of the staff; only a member's post is authored by a tenant."""

        for rec in self:
            if not rec.is_member_post and not rec.author_id.user_ids.filtered(lambda u: not u.share):
                raise UserError(_(
                    "%(post)s is a business centre post, so its author must be one of "
                    "your staff, not %(author)s.", post=rec.name, author=rec.author_id.name))

    # ------------------------------------------------------------------------------
    #   MARK: BUTTON ACTION METHODS
    # ------------------------------------------------------------------------------
    def action_publish(self):
        """Put the post on the feed. Approving a member's post tells them;
        an important announcement is emailed once to the members concerned."""

        for rec in self:
            if rec.state not in ('draft', 'pending'):
                raise UserError(_("Only a draft or a post awaiting approval can be published."))
        approved = self.filtered(lambda p: p.state == 'pending')
        self.write({
            'state': 'published',
            'published_at': fields.Datetime.now(),
            'moderated_by_id': self.env.uid,
            'reject_reason': False,
        })
        approved.activity_feedback([REVIEW_ACTIVITY], feedback=_("Published"))
        approved._bc_email_author('business_center_community.mail_template_post_published')
        self._bc_email_important()

    def action_reject(self):
        """Refuse a member's post, with a reason they are sent."""

        for rec in self:
            if rec.state != 'pending':
                raise UserError(_("Only a post awaiting approval can be rejected."))
            if not (rec.reject_reason or '').strip():
                raise UserError(_(
                    "Write the Rejection Reason first; it is sent to the member."))
        self.write({'state': 'rejected', 'moderated_by_id': self.env.uid})
        self.activity_feedback([REVIEW_ACTIVITY], feedback=_("Rejected"))
        self._bc_email_author('business_center_community.mail_template_post_rejected')

    def action_unpublish(self):
        """Take a published post off the feed, back to draft."""

        for rec in self:
            if rec.state != 'published':
                raise UserError(_("Only a published post can be taken off the feed."))
        self.write({'state': 'draft'})

    # ------------------------------------------------------------------------------
    #   MARK: HELPER METHODS
    # ------------------------------------------------------------------------------
    @api.model
    def _bc_member_centers(self, partner):
        """The business centres ``partner``'s company is a member of."""

        return partner.commercial_partner_id.sudo().bc_center_ids

    @api.model
    def _bc_portal_domain(self, partner):
        """Posts on ``partner``'s feed: published, not expired, for one of
        their company's centres or for every centre, and either for the
        whole centre or kept to their own company."""

        today = self.env.company._bc_today()
        return [
            ('state', '=', 'published'),
            '|', ('expires_on', '=', False), ('expires_on', '>=', today),
            '|', ('center_id', '=', False),
                 ('center_id', 'in', self._bc_member_centers(partner).ids),
            '|', ('audience', '=', 'center'),
                 ('author_company_id', '=', partner.commercial_partner_id.id),
        ]

    def _bc_visible_to(self, partner):
        """Whether ``partner`` may open this post: it is on their feed, or it
        is their own (whatever its state)."""

        self.ensure_one()
        return self.author_id == partner or bool(self.filtered_domain(self._bc_portal_domain(partner)))

    def _bc_audience_partners(self):
        """The members this post concerns: portal tenants whose company is a
        member of the post's centre (every tenant when it has no centre),
        narrowed to the author's company for a company-only post."""

        self.ensure_one()
        users = self.env['res.users'].sudo().search([('share', '=', True)]).filtered(
            lambda u: u.has_group(TENANT_GROUP))
        partners = users.partner_id.filtered('email')
        if self.audience == 'company':
            partners = partners.filtered(
                lambda p: p.commercial_partner_id == self.author_company_id)
        if not self.center_id:
            return partners
        return partners.filtered(lambda p: self.center_id in self._bc_member_centers(p))

    def _bc_send(self, template_xmlid, partners):
        """Queue the template for ``partners`` (one email each) and note it
        in the chatter. Kept out of the conversation, which is the members'."""

        self.ensure_one()
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        partners = partners.filtered('email')
        if not (template and partners):
            return
        template.send_mail(self.id, email_values={
            'recipient_ids': [(4, pid) for pid in partners.ids],
        })
        self.message_post(body=_("%(template)s emailed to %(count)s member(s).",
                                 template=template.name, count=len(partners)))

    def _bc_email_author(self, template_xmlid):
        """Tell the member who wrote the post what was decided."""

        for rec in self.filtered('is_member_post'):
            rec._bc_send(template_xmlid, rec.author_id)

    def _bc_email_important(self):
        """Email an important announcement, once, to the members concerned."""

        for rec in self.filtered(lambda p: p.post_type == 'announcement' and p.is_important
                                 and not p.important_sent):
            rec._bc_send('business_center_community.mail_template_post_announcement',
                         rec._bc_audience_partners())
            rec.important_sent = True
            
    def _bc_reviewer(self):
        """Who approves this member's post: the centre's manager, else the
        company's Community Moderator, else the company's first Business
        Center Manager. Never a portal user: a post shared from the portal
        is created by the member, so the current user cannot be the
        fallback."""

        self.ensure_one()
        company = (self.center_id.company_id or self.company_id).sudo()
        for user in (self.center_id.manager_id, company.bc_community_moderator_id):
            if user and user.active and not user.share:
                return user
        managers = self.env['res.users'].sudo().search(
            [('share', '=', False), ('company_ids', 'in', company.ids)], order='id'
        ).filtered(lambda u: u.has_group('business_center.group_bc_manager'))
        return managers[:1] or self.env.ref('base.user_admin')

    def _bc_request_review(self):
        """Ask the centre's manager to approve or reject a member's post."""

        for rec in self:
            rec.activity_schedule(
                REVIEW_ACTIVITY,
                summary=_("Review post: %s", rec.name),
                note=_("%(member)s (%(company)s) shared a post on the community feed. "
                       "Publish it, or write a reason and reject it.",
                       member=rec.author_id.name, company=rec.author_company_id.name),
                user_id=rec._bc_reviewer().id,
            )

    def _bc_create_images(self, images):
        """Store uploaded photos as attachments of this post.

        :param images: [(filename, bytes)], as read from the upload
        :return: the created ir.attachment records
        """

        self.ensure_one()
        images = [(name, content) for name, content in images if content]
        if len(images) > MAX_PHOTOS:
            raise UserError(_("Please add at most %s photos.", MAX_PHOTOS))
        vals_list = []
        for name, content in images:
            if len(content) > MAX_PHOTO_BYTES:
                raise UserError(_("%s is larger than 5 MB.", name))
            mimetype = guess_mimetype(content)
            if mimetype not in IMAGE_MIMETYPES:
                raise UserError(_("%s is not a photo (PNG, JPEG, GIF or WebP).", name))
            vals_list.append({
                'name': name,
                'raw': content,
                'mimetype': mimetype,
                'res_model': self._name,
                'res_id': self.id,
            })
        return self.env['ir.attachment'].sudo().create(vals_list)

    @api.model
    def _bc_create_member_post(self, partner, center, title, text, images=(),
                               audience='center'):
        """A member shares a post with their centre: text, photos or both.
        Depending on the company's setting it waits for approval or is
        published at once.

        :param images: [(filename, bytes)]
        """

        policy = center.company_id or self.env.company
        title, text = (title or '').strip(), (text or '').strip()
        images = [(name, content) for name, content in images if content]
        if not policy.bc_community_member_posts:
            raise UserError(_("Posting on the community feed is not open to members."))
        if not center or center not in self._bc_member_centers(partner):
            raise UserError(_("Pick one of your business centres."))
        if audience not in dict(AUDIENCES):
            raise UserError(_("Pick who can see your post."))
        if not title:
            raise UserError(_("Give your post a title."))
        if not (text or images):
            raise UserError(_("Write something or add a photo."))

        post = self.create({
            'name': title,
            'post_type': MEMBER_POST_TYPE,
            'body': plaintext2html(text) if text else False,
            'author_id': partner.id,
            'is_member_post': True,
            'center_id': center.id,
            'audience': audience,
            'company_id': policy.id,
            # Awaiting approval, or a draft published just below.
            'state': 'pending' if policy.bc_community_moderation else 'draft',
        })
        attachments = post._bc_create_images(images)
        if attachments:
            post.photo_ids = [(4, attachment.id) for attachment in attachments]
        if policy.bc_community_moderation:
            post._bc_request_review()
        else:
            post.action_publish()
        return post

    def _bc_add_comment(self, partner, body):
        """A member comments on a published post."""

        self.ensure_one()
        body = (body or '').strip()
        if not body:
            raise UserError(_("Please write a comment."))
        if self.state != 'published' or not self.allow_comments:
            raise UserError(_("Comments are closed on this post."))
        self.message_post(
            body=plaintext2html(body),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            author_id=partner.id,
        )

    def _bc_portal_messages(self):
        """The comments members may see: customer messages only, never
        internal notes or field tracking; oldest first."""

        self.ensure_one()
        return self.message_ids.filtered(
            lambda m: m.message_type == 'comment'
            and m.subtype_id and not m.subtype_id.internal and not m.is_internal
        ).sorted('id')
