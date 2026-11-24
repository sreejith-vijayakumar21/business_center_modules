# -*- coding: utf-8 -*-

from collections import OrderedDict
from urllib.parse import urlencode

from odoo import _, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.addons.business_center_portal.controllers.portal import (
    BusinessCenterPortal, TENANT_EMPLOYEE_GROUP)

POSTS_PER_PAGE = 10


class BusinessCenterCommunityPortal(BusinessCenterPortal):
    """The community feed in the tenant portal: read, comment and share.

    Like the booking pages, records are read with sudo() inside the member's
    own scope only, and that scope (which posts a member sees, what they may
    post, whether it needs approval) is the post model's.
    """

    # ------------------------------------------------------------------------------
    #   MARK: HOME COUNTER
    # ------------------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'community_count' in counters:
            user = request.env.user
            allowed = not user.share or user.has_group(TENANT_EMPLOYEE_GROUP)
            Post = request.env['business.center.post'].sudo()
            values['community_count'] = (
                Post.search_count(Post._bc_portal_domain(user.partner_id)) if allowed else 0)
        return values

    # ------------------------------------------------------------------------------
    #   MARK: SCOPE HELPERS
    # ------------------------------------------------------------------------------
    def _bc_get_post_sudo(self, post_id):
        """Return (post_sudo, None) when the member may open the post, else
        (None, redirect response)."""

        denied = self._bc_booking_access_denied()
        if denied:
            return None, denied
        post = request.env['business.center.post'].sudo().browse(post_id).exists()
        if not (post and post._bc_visible_to(request.env.user.partner_id)):
            return None, request.redirect('/my/community')
        return post, None

    def _post_redirect(self, post_id, error=None):
        """Back to the post page, with ``error`` shown at the top if any."""

        url = '/my/community/%s' % post_id
        return request.redirect('%s?%s' % (url, urlencode({'error': error})) if error else url)

    @staticmethod
    def _community_centers():
        """The centres the member may post to."""

        return request.env['business.center.post'].sudo()._bc_member_centers(
            request.env.user.partner_id).sorted('name')

    @staticmethod
    def _community_can_post():
        """Whether member posting is switched on for the member's company context."""

        return request.env.company.sudo().bc_community_member_posts

    @staticmethod
    def _community_uploaded_images():
        """Photos sent with the form as [(filename, bytes)]; the post model
        checks their number, size and type."""

        files = request.httprequest.files.getlist('photos')
        return [(f.filename, f.read()) for f in files if f and f.filename]

    # ------------------------------------------------------------------------------
    #   MARK: FEED AND POST
    # ------------------------------------------------------------------------------
    def _community_searchbar_filters(self):
        partner = request.env.user.partner_id
        return {
            'all': {'label': _('Everything'), 'domain': []},
            'announcement': {'label': _('Announcements'), 'domain': [('post_type', '=', 'announcement')]},
            'update': {'label': _('Updates'), 'domain': [('post_type', '=', 'update')]},
            'photo': {'label': _('Photos'), 'domain': [('post_type', '=', 'photo')]},
            # The member's own posts, whatever their state.
            'mine': {'label': _('My Posts'), 'domain': [('author_id', '=', partner.id)], 'own': True},
        }

    @http.route(['/my/community', '/my/community/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_community(self, page=1, filterby=None, search=None, **kw):
        """The feed: pinned posts first, then the newest."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        Post = request.env['business.center.post'].sudo()
        filters = self._community_searchbar_filters()
        filterby = filterby if filterby in filters else 'all'
        chosen = filters[filterby]

        domain = list(chosen['domain'])
        if not chosen.get('own'):
            domain += Post._bc_portal_domain(request.env.user.partner_id)
        if search:
            domain += ['|', ('name', 'ilike', search), ('body', 'ilike', search)]

        pager = portal_pager(
            url='/my/community',
            url_args={'filterby': filterby, 'search': search},
            total=Post.search_count(domain),
            page=page,
            step=POSTS_PER_PAGE,
        )
        posts = Post.search(domain, limit=POSTS_PER_PAGE, offset=pager['offset'])

        values = self._prepare_portal_layout_values()
        values.update({
            'posts': posts,
            'page_name': 'community',
            'pager': pager,
            'default_url': '/my/community',
            'searchbar_filters': OrderedDict(filters.items()),
            'filterby': filterby,
            'searchbar_inputs': {'all': {'input': 'all', 'label': _('Search in posts')}},
            'search_in': 'all',
            'search': search,
            'can_post': self._community_can_post() and bool(self._community_centers()),
        })
        return request.render('business_center_community.portal_my_community', values)

    @http.route(['/my/community/<int:post_id>'], type='http', auth='user', website=True)
    def portal_community_post(self, post_id, **kw):
        """One post with its photos and comments."""

        post, redirect = self._bc_get_post_sudo(post_id)
        if redirect:
            return redirect
        values = self._prepare_portal_layout_values()
        values.update({
            'post': post,
            'page_name': 'community',
            'comments': post._bc_portal_messages(),
            'can_comment': post.state == 'published' and post.allow_comments,
            'my_partner': request.env.user.partner_id,
            'error': kw.get('error', ''),
        })
        return request.render('business_center_community.portal_community_post', values)

    # ------------------------------------------------------------------------------
    #   MARK: SHARE A POST
    # ------------------------------------------------------------------------------
    def _community_form_values(self, **extra):
        """Everything the "share a post" form needs."""

        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'community',
            'post_form': True,
            'centers': self._community_centers(),
            'moderated': request.env.company.sudo().bc_community_moderation,
            'form': {'post_type': 'update', 'audience': 'center'},
            'my_company': request.env.user.partner_id.commercial_partner_id,
            'error': '',
        })
        values.update(extra)
        return values

    @http.route(['/my/community/new'], type='http', auth='user', website=True, methods=['GET'])
    def portal_community_new(self, **kw):
        """The "share a post" form."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        if not (self._community_can_post() and self._community_centers()):
            return request.redirect('/my/community')
        return request.render('business_center_community.portal_community_form',
                              self._community_form_values())

    @http.route(['/my/community/new'], type='http', auth='user', website=True, methods=['POST'])
    def portal_community_submit(self, **post):
        """Create the member's post. Who may post what, and whether it needs
        approval, are the post model's rules."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        form = {key: (post.get(key) or '').strip()
                for key in ('post_type', 'center_id', 'title', 'text', 'audience')}
        centers = self._community_centers()
        center = centers.filtered(lambda c: c.id == self._bc_to_int(form['center_id']))[:1] or centers[:1]
        try:
            record = request.env['business.center.post'].sudo()._bc_create_member_post(
                request.env.user.partner_id, center, form['post_type'], form['title'],
                form['text'], self._community_uploaded_images(),
                audience=form['audience'] or 'center')
            request.env.flush_all()
        except (UserError, ValidationError) as exc:
            request.env.cr.rollback()
            return request.render('business_center_community.portal_community_form',
                                  self._community_form_values(form=form, error=exc.args[0]))
        return self._post_redirect(record.id)

    # ------------------------------------------------------------------------------
    #   MARK: COMMENTS
    # ------------------------------------------------------------------------------
    @http.route(['/my/community/<int:post_id>/comment'], type='http', auth='user',
                website=True, methods=['POST'])
    def portal_community_comment(self, post_id, body=None, **kw):
        """The member comments on a post."""

        post, redirect = self._bc_get_post_sudo(post_id)
        if redirect:
            return redirect
        try:
            post._bc_add_comment(request.env.user.partner_id, body)
            request.env.flush_all()
        except (UserError, ValidationError) as exc:
            request.env.cr.rollback()
            return self._post_redirect(post_id, exc.args[0])
        return request.redirect('/my/community/%s#comments' % post_id)

    # ------------------------------------------------------------------------------
    #   MARK: PHOTOS
    # ------------------------------------------------------------------------------
    @http.route(['/my/community/<int:post_id>/photo/<int:attachment_id>'], type='http',
                auth='user', methods=['GET'])
    def portal_community_photo(self, post_id, attachment_id, size=None, **kw):
        """A photo of a post the member may see. Portal users cannot read
        attachments themselves, so it is served here after checking it
        belongs to the post."""

        post, redirect = self._bc_get_post_sudo(post_id)
        if redirect:
            return request.not_found()
        attachment = post.photo_ids.filtered(lambda a: a.id == attachment_id)
        if not attachment:
            return request.not_found()
        side = 480 if size == 'thumb' else 0
        return request.env['ir.binary']._get_image_stream_from(
            attachment, 'raw', width=side, height=side, crop=bool(side)).get_response()
