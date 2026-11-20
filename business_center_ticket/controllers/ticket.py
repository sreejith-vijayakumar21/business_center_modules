# -*- coding: utf-8 -*-

from collections import OrderedDict
from urllib.parse import urlencode

from odoo import _, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.addons.business_center_portal.controllers.portal import (
    BusinessCenterPortal, TENANT_EMPLOYEE_GROUP)

OPEN_STATES = ('new', 'in_progress', 'waiting')


class BusinessCenterTicketPortal(BusinessCenterPortal):
    """Support tickets in the tenant portal: list, raise, follow, answer and
    reopen.

    Like the booking pages, records are read with sudo() inside the member's
    own scope only (their own tickets, or the company's for a corporate
    admin), and every rule (assignment, targets, allowed steps, photo
    checks) is the ticket model's.
    """

    # ------------------------------------------------------------------------------
    #   MARK: HOME COUNTER
    # ------------------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'ticket_count' in counters:
            user = request.env.user
            allowed = not user.share or user.has_group(TENANT_EMPLOYEE_GROUP)
            values['ticket_count'] = (
                request.env['business.center.ticket'].sudo().search_count(
                    self._ticket_domain() + [('state', 'in', OPEN_STATES)]) if allowed else 0)
        return values

    # ------------------------------------------------------------------------------
    #   MARK: SCOPE HELPERS
    # ------------------------------------------------------------------------------
    def _ticket_domain(self):
        """Tickets this member may see: the company's for a corporate admin,
        the ones they reported for an employee."""

        partner = request.env.user.partner_id
        if self._bc_is_tenant_admin():
            return [('commercial_partner_id', '=', partner.commercial_partner_id.id)]
        return [('partner_id', '=', partner.id)]

    def _bc_get_ticket_sudo(self, ticket_id):
        """Return (ticket_sudo, None) when the member may see the ticket,
        else (None, redirect response)."""

        denied = self._bc_booking_access_denied()
        if denied:
            return None, denied
        ticket = request.env['business.center.ticket'].sudo().browse(ticket_id).exists()
        ticket = ticket.filtered_domain(self._ticket_domain())
        if not ticket:
            return None, request.redirect('/my/tickets')
        return ticket, None

    def _ticket_redirect(self, ticket_id, error=None):
        """Back to the ticket page, with ``error`` shown at the top if any."""

        url = '/my/tickets/%s' % ticket_id
        return request.redirect('%s?%s' % (url, urlencode({'error': error})) if error else url)

    @staticmethod
    def _ticket_categories():
        return request.env['business.center.ticket.category'].sudo().search([])

    @staticmethod
    def _ticket_unit_options(contract):
        """The places a ticket on ``contract`` may be about, as (value, label)
        pairs for the form: its leased offices and desks, its centre's
        meeting rooms."""

        if not contract:
            return []
        spaces, desks = contract._bc_ticket_units()
        options = [('space-%s' % s.id, s.name) for s in spaces.sorted('name')]
        options += [('desk-%s' % d.id, '%s · %s' % (d.name, d.space_id.name)) for d in desks.sorted('name')]
        return options

    def _ticket_unit_values(self, contract, value):
        """The space/desk fields for the option picked in the form. Only an
        option of the member's own contract is accepted; anything else means
        "general"."""

        if value not in dict(self._ticket_unit_options(contract)):
            return {}
        kind, _sep, record_id = value.partition('-')
        if kind == 'desk':
            desk = request.env['business.center.desk'].sudo().browse(int(record_id))
            return {'desk_id': desk.id, 'space_id': desk.space_id.id}
        return {'space_id': int(record_id)}

    @staticmethod
    def _ticket_uploaded_images():
        """Photos sent with the form as [(filename, bytes)]; the ticket model
        checks their number, size and type."""

        files = request.httprequest.files.getlist('photos')
        return [(f.filename, f.read()) for f in files if f and f.filename]

    # ------------------------------------------------------------------------------
    #   MARK: LIST AND DETAIL
    # ------------------------------------------------------------------------------
    def _ticket_searchbar_sortings(self):
        return {
            'date': {'label': _('Newest'), 'order': 'id desc'},
            'priority': {'label': _('Priority'), 'order': 'priority desc, id desc'},
            'state': {'label': _('Status'), 'order': 'state, id desc'},
        }

    def _ticket_searchbar_filters(self):
        return {
            'all': {'label': _('All'), 'domain': []},
            'open': {'label': _('Open'), 'domain': [('state', 'in', OPEN_STATES)]},
            'waiting': {'label': _('Waiting on You'), 'domain': [('state', '=', 'waiting')]},
            'resolved': {'label': _('Resolved'), 'domain': [('state', 'in', ('resolved', 'closed'))]},
        }

    def _ticket_searchbar_inputs(self):
        return {
            'all': {'input': 'all', 'label': _('Search in Ticket and Subject')},
            'category': {'input': 'category', 'label': _('Search in Category')},
        }

    def _ticket_search_domain(self, search_in, search):
        if search_in == 'category':
            return [('category_id.name', 'ilike', search)]
        return ['|', ('name', 'ilike', search), ('subject', 'ilike', search)]

    @http.route(['/my/tickets', '/my/tickets/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_tickets(self, page=1, sortby=None, filterby=None,
                          search=None, search_in='all', **kw):
        """The list of the member's tickets."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        Ticket = request.env['business.center.ticket'].sudo()
        sortings = self._ticket_searchbar_sortings()
        filters = self._ticket_searchbar_filters()
        inputs = self._ticket_searchbar_inputs()
        sortby = sortby if sortby in sortings else 'date'
        filterby = filterby if filterby in filters else 'all'

        domain = self._ticket_domain() + filters[filterby]['domain']
        if search and search_in in inputs:
            domain += self._ticket_search_domain(search_in, search)

        pager = portal_pager(
            url='/my/tickets',
            url_args={'sortby': sortby, 'filterby': filterby,
                      'search': search, 'search_in': search_in},
            total=Ticket.search_count(domain),
            page=page,
            step=self._items_per_page,
        )
        tickets = Ticket.search(domain, order=sortings[sortby]['order'],
                                limit=self._items_per_page, offset=pager['offset'])

        values = self._prepare_portal_layout_values()
        values.update({
            'tickets': tickets,
            'page_name': 'ticket',
            'pager': pager,
            'default_url': '/my/tickets',
            'searchbar_sortings': sortings,
            'sortby': sortby,
            'searchbar_filters': OrderedDict(sorted(filters.items())),
            'filterby': filterby,
            'searchbar_inputs': inputs,
            'search_in': search_in,
            'search': search,
            'is_tenant_admin': self._bc_is_tenant_admin(),
        })
        return request.render('business_center_ticket.portal_my_tickets', values)

    @http.route(['/my/tickets/<int:ticket_id>'], type='http', auth='user', website=True)
    def portal_my_ticket_detail(self, ticket_id, **kw):
        """One ticket with its conversation."""

        ticket, redirect = self._bc_get_ticket_sudo(ticket_id)
        if redirect:
            return redirect
        values = self._prepare_portal_layout_values()
        values.update({
            'ticket': ticket,
            'page_name': 'ticket',
            'messages': ticket._bc_portal_messages(),
            'can_reply': ticket.state in OPEN_STATES,
            'can_reopen': ticket._bc_can_reopen(),
            'reopen_days': ticket.company_id.bc_ticket_reopen_days,
            'my_partner': request.env.user.partner_id,
            'error': kw.get('error', ''),
        })
        return request.render('business_center_ticket.portal_ticket_page', values)

    # ------------------------------------------------------------------------------
    #   MARK: NEW TICKET
    # ------------------------------------------------------------------------------
    def _ticket_form_values(self, contracts, contract, **extra):
        """Everything the "raise a ticket" form needs."""

        Ticket = request.env['business.center.ticket']
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'ticket',
            'ticket_form': True,
            'contracts': contracts,
            'contract': contract,
            'categories': self._ticket_categories(),
            'priorities': Ticket._fields['priority']._description_selection(request.env),
            'unit_options': self._ticket_unit_options(contract),
            'form': {'priority': '1'},
            'error': '',
        })
        values.update(extra)
        return values

    def _ticket_form_contract(self, contract_id):
        """(contracts, chosen contract) inside the member's own scope."""

        contracts = self._bc_member_contracts()
        contract = contracts.filtered(
            lambda c: c.id == self._bc_to_int(contract_id))[:1] or contracts[:1]
        return contracts, contract

    @http.route(['/my/tickets/new'], type='http', auth='user', website=True, methods=['GET'])
    def portal_ticket_new(self, contract_id=None, **kw):
        """The "raise a ticket" form. Changing the contract reloads it, so
        the places offered are that contract's."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        contracts, contract = self._ticket_form_contract(contract_id)
        if not contracts:
            return request.render('business_center_ticket.portal_ticket_no_contract',
                                  {'page_name': 'ticket', 'ticket_form': True})
        return request.render('business_center_ticket.portal_ticket_form',
                              self._ticket_form_values(contracts, contract))

    @http.route(['/my/tickets/new'], type='http', auth='user', website=True, methods=['POST'])
    def portal_ticket_submit(self, **post):
        """Create the ticket inside the member's own scope. Assignment, the
        response target and the notifications are the ticket model's."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        contracts, contract = self._ticket_form_contract(post.get('contract_id'))
        form = {key: (post.get(key) or '').strip()
                for key in ('subject', 'description', 'priority', 'category_id', 'unit', 'topic')}

        def fail(message):
            return request.render('business_center_ticket.portal_ticket_form',
                                  self._ticket_form_values(contracts, contract, form=form, error=message))

        Ticket = request.env['business.center.ticket'].sudo()
        category = self._ticket_categories().filtered(
            lambda c: c.id == self._bc_to_int(form['category_id']))
        if not contract:
            return fail(_("Pick one of your running contracts."))
        if not contract.center_id:
            return fail(_("This contract has no business centre yet. Please contact the business centre."))
        if not category:
            return fail(_("Pick what the problem is about."))
        if category.ask_topic and not form['topic']:
            return fail(_("Tell us in a few words what the problem is about."))
        if not form['subject'] or not form['description']:
            return fail(_("Give the ticket a subject and describe the problem."))
        if form['priority'] not in dict(Ticket._fields['priority'].selection):
            form['priority'] = '1'

        try:
            ticket = Ticket.create(dict({
                'subject': form['subject'],
                'description': form['description'],
                'priority': form['priority'],
                'category_id': category.id,
                'topic': form['topic'] if category.ask_topic else False,
                'partner_id': request.env.user.partner_id.id,
                'contract_id': contract.id,
                'center_id': contract.center_id.id,
            }, **self._ticket_unit_values(contract, form['unit'])))
            ticket._bc_add_photos(self._ticket_uploaded_images())
            request.env.flush_all()
        except (UserError, ValidationError) as exc:
            request.env.cr.rollback()
            return fail(exc.args[0])
        return self._ticket_redirect(ticket.id)

    # ------------------------------------------------------------------------------
    #   MARK: REPLY AND REOPEN
    # ------------------------------------------------------------------------------
    @http.route(['/my/tickets/<int:ticket_id>/reply'], type='http', auth='user',
                website=True, methods=['POST'])
    def portal_ticket_reply(self, ticket_id, body=None, **post):
        """The member writes on their ticket, with optional photos."""

        ticket, redirect = self._bc_get_ticket_sudo(ticket_id)
        if redirect:
            return redirect
        try:
            ticket._bc_customer_reply(request.env.user.partner_id, body, self._ticket_uploaded_images())
            request.env.flush_all()
        except (UserError, ValidationError) as exc:
            request.env.cr.rollback()
            return self._ticket_redirect(ticket_id, exc.args[0])
        return self._ticket_redirect(ticket_id)

    @http.route(['/my/tickets/<int:ticket_id>/reopen'], type='http', auth='user',
                website=True, methods=['POST'])
    def portal_ticket_reopen(self, ticket_id, reason=None, **post):
        """The member says a resolved ticket is not solved."""

        ticket, redirect = self._bc_get_ticket_sudo(ticket_id)
        if redirect:
            return redirect
        try:
            ticket._bc_customer_reopen(request.env.user.partner_id, reason)
            request.env.flush_all()
        except (UserError, ValidationError) as exc:
            request.env.cr.rollback()
            return self._ticket_redirect(ticket_id, exc.args[0])
        return self._ticket_redirect(ticket_id)

    # ------------------------------------------------------------------------------
    #   MARK: PHOTOS
    # ------------------------------------------------------------------------------
    @http.route(['/my/tickets/<int:ticket_id>/photo/<int:attachment_id>'], type='http',
                auth='user', methods=['GET'])
    def portal_ticket_photo(self, ticket_id, attachment_id, size=None, **kw):
        """A photo of one of the member's tickets or its conversation.
        Portal users cannot read attachments themselves, so it is served
        here after checking it belongs to the ticket."""

        ticket, redirect = self._bc_get_ticket_sudo(ticket_id)
        if redirect:
            return request.not_found()
        attachment = ticket._bc_portal_attachments().filtered(lambda a: a.id == attachment_id)
        if not attachment:
            return request.not_found()
        Binary = request.env['ir.binary']
        if not (attachment.mimetype or '').startswith('image/'):
            # Staff may attach a document to a message: download it as it is.
            return Binary._get_stream_from(attachment, 'raw').get_response(as_attachment=True)
        side = 160 if size == 'thumb' else 0
        return Binary._get_image_stream_from(
            attachment, 'raw', width=side, height=side, crop=bool(side)).get_response()
