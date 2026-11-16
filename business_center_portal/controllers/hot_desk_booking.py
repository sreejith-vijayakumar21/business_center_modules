# -*- coding: utf-8 -*-

from collections import OrderedDict
from urllib.parse import urlencode

from psycopg2 import IntegrityError

from odoo import _, fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import pager as portal_pager

from .portal import BusinessCenterPortal, TENANT_EMPLOYEE_GROUP

HOT_DESK_LINK_KEY = 'bc_hot_desk'


class BusinessCenterHotDeskPortal(BusinessCenterPortal):
    """Hot desk bookings in the tenant portal: list, detail, cancel, the
    booking form and the data its floor picker reads.

    Records are read with sudo() inside the member's own scope only: their
    company's running contracts and the centres of those contracts. Portal
    users therefore need no access to the inventory or floor plan models.
    """

    # ------------------------------------------------------------------------------
    #   MARK: HOME COUNTER
    # ------------------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'hot_desk_count' in counters:
            user = request.env.user
            allowed = not user.share or user.has_group(TENANT_EMPLOYEE_GROUP)
            values['hot_desk_count'] = (
                request.env['business.center.desk.booking'].sudo().search_count(
                    self._hot_desk_domain()) if allowed else 0)
        return values

    # ------------------------------------------------------------------------------
    #   MARK: SCOPE HELPERS
    # ------------------------------------------------------------------------------
    def _hot_desk_domain(self):
        """Bookings this member may see: the company's for a corporate admin;
        for an employee, those they made or the desk is for."""

        user = request.env.user
        company = user.partner_id.commercial_partner_id
        domain = [('contract_id.partner_id', 'child_of', company.id)]
        if not self._bc_is_tenant_admin():
            domain += ['|', ('user_id', '=', user.id), ('partner_id', '=', user.partner_id.id)]
        return domain

    def _hot_desk_contracts(self):
        """Running contracts this member may bill a hot desk to: any of the
        company's for a corporate admin, the ones they are named on for an
        employee. Desk-only contracts qualify too."""

        user = request.env.user
        domain = [
            ('partner_id', 'child_of', user.partner_id.commercial_partner_id.id),
            ('state', '=', 'active'),
        ]
        if not self._bc_is_tenant_admin():
            domain.append(('contact_ids', 'in', [user.partner_id.id]))
        return request.env['business.center.contract'].sudo().search(domain)

    def _hot_desk_contract(self, contract_id):
        """One of the member's contracts, or an empty recordset."""

        return self._hot_desk_contracts().filtered(
            lambda c: c.id == self._bc_to_int(contract_id))[:1]

    def _hot_desk_people(self, contract):
        """Who a desk may be booked for: any colleague on the contract and
        the member themselves, all of the contract's own company."""

        people = contract.contact_ids | request.env.user.partner_id
        return people.filtered(
            lambda p: p.commercial_partner_id == contract.partner_id).sorted('name')

    def _free_hot_desks(self, contract, booking_date, start, end):
        """Open hot desks of the contract's centre not held during the slot,
        decided by the booking model itself (available_desk_ids)."""

        if not contract.center_id:
            return request.env['business.center.desk'].sudo()
        preview = request.env['business.center.desk.booking'].sudo().new({
            'center_id': contract.center_id.id,
            'booking_date': booking_date,
            'start_time': start or 0.0,
            'end_time': end or 0.0,
        })
        return preview.available_desk_ids.sorted('name')
    
    def _hot_desk_sites(self, contract, free_desks):
        """Floors of the contract's centre that draw its hot desks, each
        counting the desks free for the slot. A floor stays listed when all
        its desks are booked, so the member sees them in red instead of the
        floor vanishing."""

        if not contract.center_id:
            return []
        hot_desks = request.env['business.center.desk'].sudo().search([
            ('desk_type', '=', 'hot'),
            ('center_id', '=', contract.center_id.id),
        ])
        if not hot_desks:
            return []
        Floor = request.env['business.center.floor'].sudo()
        sites = Floor.bc_get_picker_sites(HOT_DESK_LINK_KEY, hot_desks.ids)
        free_sites = Floor.bc_get_picker_sites(HOT_DESK_LINK_KEY, free_desks.ids) if free_desks else []
        free_by_plan = {plan['id']: plan['pickable'] for site in free_sites for plan in site['plans']}
        # The note counts free desks missing from every layout: take it from the free call.
        free_notes = {site['id']: site['note'] for site in free_sites}
        for site in sites:
            site['note'] = free_notes.get(site['id'], False)
            for plan in site['plans']:
                plan['pickable'] = free_by_plan.get(plan['id'], 0)
        return sites

    def _hot_desk_plan(self, plan_id, contract):
        """The floor plan when it belongs to the contract's centre, else an
        empty recordset."""

        plan = request.env['workspace.floor.plan'].sudo().browse(plan_id).exists()
        if contract and plan and plan.bc_floor_id.center_id == contract.center_id:
            return plan
        return plan.browse()

    def _hot_desk_slot_states(self, plan, selection):
        """'free', 'booked' or 'closed' for every hot desk drawn on ``plan``,
        keyed by shape id, for the chosen slot. Decided here, not in the
        browser, from the same data as the desk dropdown."""

        contract = selection['contract']
        objects = request.env['workspace.floor.plan.object'].sudo().search([
            ('plan_id', '=', plan.id),
            ('link_key', '=', HOT_DESK_LINK_KEY),
            ('link_res_id', '!=', False),
        ])
        desks = request.env['business.center.desk'].sudo().browse(
            objects.mapped('link_res_id')).exists().filtered(
            lambda d: d.center_id == contract.center_id)
        held = request.env['business.center.desk.booking'].sudo()._bc_held_desks(
            desks, selection['booking_date'], selection['start'] or 0.0, selection['end'] or 0.0)
        free = selection['desks']
        states = {}
        for obj in objects:
            desk = desks.filtered(lambda d: d.id == obj.link_res_id)
            if desk:
                states[obj.id] = 'free' if desk in free else ('booked' if desk in held else 'closed')
        return states

    def _hot_desk_selection(self, values):
        """Contract, date, times, free desks and people for the form, from
        what was posted or asked. Ids are only looked up inside the member's
        own scope, never trusted; malformed values fall back."""

        contracts = self._hot_desk_contracts()
        contract = contracts.filtered(
            lambda c: c.id == self._bc_to_int(values.get('contract_id')))[:1] or contracts[:1]
        booking_date = self._bc_parse_date(values.get('booking_date')) or self._bc_today()
        start = self._bc_parse_time(values.get('start_time'))
        end = self._bc_parse_time(values.get('end_time'))
        return {
            'contracts': contracts,
            'contract': contract,
            'booking_date': booking_date,
            'start': start,
            'end': end,
            'desks': self._free_hot_desks(contract, booking_date, start, end),
            'people': self._hot_desk_people(contract),
        }

    @staticmethod
    def _hot_desk_option(desk):
        """A desk as the form's dropdown and the picker show it."""

        return {
            'id': desk.id,
            'name': '%s · %s' % (desk.name, desk.space_id.name),
            'rate': desk.hourly_rate,
        }

    def _bc_get_hot_desk_sudo(self, booking_id):
        """Return (booking_sudo, None) when the member may see the booking,
        else (None, redirect response)."""

        denied = self._bc_booking_access_denied()
        if denied:
            return None, denied
        booking = request.env['business.center.desk.booking'].sudo().browse(booking_id).exists()
        booking = booking.filtered_domain(self._hot_desk_domain())
        if not booking:
            return None, request.redirect('/my/hot-desks')
        return booking, None

    # ------------------------------------------------------------------------------
    #   MARK: LIST AND DETAIL
    # ------------------------------------------------------------------------------
    def _hot_desk_searchbar_sortings(self):
        return {
            'date': {'label': _('Date'), 'order': 'booking_date desc, start_time desc'},
            'name': {'label': _('Reference'), 'order': 'name desc'},
            'state': {'label': _('Status'), 'order': 'state'},
        }

    def _hot_desk_searchbar_filters(self):
        return {
            'all': {'label': _('All'), 'domain': []},
            'upcoming': {'label': _('Upcoming'), 'domain': [('state', '=', 'confirmed')]},
            'done': {'label': _('Done'), 'domain': [('state', 'in', ('checked_in', 'done'))]},
            'cancelled': {'label': _('Cancelled'),
                          'domain': [('state', 'in', ('cancelled', 'released', 'no_show'))]},
        }

    def _hot_desk_searchbar_inputs(self):
        return {
            'name': {'input': 'name', 'label': _('Search in Reference')},
            'desk': {'input': 'desk', 'label': _('Search in Desk')},
            'user': {'input': 'user', 'label': _('Search in Desk User')},
            'all': {'input': 'all', 'label': _('Search in All')},
        }

    def _hot_desk_search_domain(self, search_in, search):
        domains = {
            'name': [('name', 'ilike', search)],
            'desk': [('desk_id.name', 'ilike', search)],
            'user': [('partner_id.name', 'ilike', search)],
        }
        return domains.get(search_in) or ['|', '|', ('name', 'ilike', search),
                                          ('desk_id.name', 'ilike', search),
                                          ('partner_id.name', 'ilike', search)]

    @http.route(['/my/hot-desks', '/my/hot-desks/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_hot_desks(self, page=1, sortby=None, filterby=None,
                            search=None, search_in='all', **kw):
        """The list of the member's hot desk bookings."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        Booking = request.env['business.center.desk.booking'].sudo()
        sortings = self._hot_desk_searchbar_sortings()
        filters = self._hot_desk_searchbar_filters()
        inputs = self._hot_desk_searchbar_inputs()
        sortby = sortby if sortby in sortings else 'date'
        filterby = filterby if filterby in filters else 'all'

        domain = self._hot_desk_domain() + filters[filterby]['domain']
        if search and search_in in inputs:
            domain += self._hot_desk_search_domain(search_in, search)

        pager = portal_pager(
            url='/my/hot-desks',
            url_args={'sortby': sortby, 'filterby': filterby,
                      'search': search, 'search_in': search_in},
            total=Booking.search_count(domain),
            page=page,
            step=self._items_per_page,
        )
        bookings = Booking.search(domain, order=sortings[sortby]['order'],
                                  limit=self._items_per_page, offset=pager['offset'])

        values = self._prepare_portal_layout_values()
        values.update({
            'bookings': bookings,
            'page_name': 'hot_desk',
            'pager': pager,
            'default_url': '/my/hot-desks',
            'searchbar_sortings': sortings,
            'sortby': sortby,
            'searchbar_filters': OrderedDict(sorted(filters.items())),
            'filterby': filterby,
            'searchbar_inputs': inputs,
            'search_in': search_in,
            'search': search,
        })
        return request.render('business_center_portal.portal_my_hot_desks', values)

    @http.route(['/my/hot-desks/<int:booking_id>'], type='http', auth='user', website=True)
    def portal_my_hot_desk_detail(self, booking_id, **kw):
        """One hot desk booking."""

        booking, redirect = self._bc_get_hot_desk_sudo(booking_id)
        if redirect:
            return redirect
        reason = self._hot_desk_cancel_block_reason(booking)
        values = self._prepare_portal_layout_values()
        values.update({
            'booking': booking,
            'page_name': 'hot_desk',
            'can_cancel': not reason,
            'cancel_block_reason': reason,
            'is_tenant_admin': self._bc_is_tenant_admin(),
            'error': kw.get('error', ''),
        })
        return request.render('business_center_portal.portal_hot_desk_page', values)

    # ------------------------------------------------------------------------------
    #   MARK: CANCELLATION
    # ------------------------------------------------------------------------------
    def _hot_desk_cancel_block_reason(self, booking):
        """Why this member may not cancel this booking, or False if they may.
        Free before the start, by the person who booked, the desk user or the
        company's admin; once started, the centre decides any charge."""

        user = request.env.user
        if booking.state != 'confirmed':
            return _("Only an upcoming booking can be cancelled.")
        if not (self._bc_is_tenant_admin() or booking.user_id == user
                or booking.partner_id == user.partner_id):
            return _("Only the person who booked, the desk user or your company's "
                     "administrator can cancel this booking.")
        if booking._is_in_past():
            return _("This booking has already started. Please contact the "
                     "business centre to cancel it.")
        return False

    @http.route(['/my/hot-desks/<int:booking_id>/cancel'], type='http',
                auth='user', website=True, methods=['POST'])
    def portal_hot_desk_cancel(self, booking_id, **post):
        """Cancel an upcoming hot desk booking, free of charge."""

        booking, redirect = self._bc_get_hot_desk_sudo(booking_id)
        if redirect:
            return redirect
        reason = self._hot_desk_cancel_block_reason(booking)
        if reason:
            return request.redirect('/my/hot-desks/%s?%s' % (booking_id, urlencode({'error': reason})))
        try:
            booking.action_cancel()
            request.env.flush_all()
        except (UserError, ValidationError) as exc:
            request.env.cr.rollback()
            return request.redirect('/my/hot-desks/%s?%s' % (
                booking_id, urlencode({'error': exc.args[0]})))
        return request.redirect('/my/hot-desks/%s' % booking_id)

    # ------------------------------------------------------------------------------
    #   MARK: BOOKING FORM
    # ------------------------------------------------------------------------------
    def _hot_desk_form_values(self, selection, **extra):
        """Everything the booking form template needs."""

        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'hot_desk',
            'contracts': selection['contracts'],
            'contract': selection['contract'],
            'people': selection['people'],
            'desk_options': [self._hot_desk_option(d) for d in selection['desks']],
            'booking_date': fields.Date.to_string(selection['booking_date']),
            'start_hhmm': self._bc_float_to_hhmm(selection['start']),
            'end_hhmm': self._bc_float_to_hhmm(selection['end']),
            'today': fields.Date.to_string(self._bc_today()),
            'currency': request.env.company.currency_id,
            'desk_id': 0,
            'partner_id': request.env.user.partner_id.id,
            'error': '',
        })
        values.update(extra)
        return values

    @http.route(['/my/hot-desks/new'], type='http', auth='user', website=True, methods=['GET'])
    def portal_hot_desk_new(self, **kw):
        """The hot desk booking form."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        selection = self._hot_desk_selection(kw)
        if not selection['contracts']:
            return request.render('business_center_portal.portal_hot_desk_no_contract',
                                  {'page_name': 'hot_desk'})
        return request.render('business_center_portal.portal_hot_desk_form',
                              self._hot_desk_form_values(selection))

    @http.route(['/my/hot-desks/new'], type='http', auth='user', website=True, methods=['POST'])
    def portal_hot_desk_submit(self, **post):
        """Check the slot against the member's own scope and create a
        confirmed booking billed to the contract. Confirmed at once: a draft
        would hold nothing, so two people could claim the same desk."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        selection = self._hot_desk_selection(post)
        desk_id = self._bc_to_int(post.get('desk_id'))
        partner_id = self._bc_to_int(post.get('partner_id'))

        def fail(message):
            return request.render('business_center_portal.portal_hot_desk_form',
                                  self._hot_desk_form_values(
                                      selection, error=message,
                                      desk_id=desk_id, partner_id=partner_id))

        contract, start, end = selection['contract'], selection['start'], selection['end']
        if not contract:
            return fail(_("Pick one of your running contracts."))
        if selection['booking_date'] < self._bc_today():
            return fail(_("Bookings cannot be made for a past date."))
        if start is None or end is None:
            return fail(_("Pick a start and an end time."))
        if end <= start:
            return fail(_("The end time must be after the start time."))
        desk = selection['desks'].filtered(lambda d: d.id == desk_id)
        if not desk:
            return fail(_("That desk is not free for this time. Please pick another one."))
        person = selection['people'].filtered(lambda p: p.id == partner_id)
        if not person:
            return fail(_("Pick who will use the desk."))

        Booking = request.env['business.center.desk.booking'].sudo()
        try:
            booking = Booking.create({
                'partner_id': person.id,
                'user_id': request.env.user.id,
                'contract_id': contract.id,
                'center_id': desk.center_id.id,
                'space_id': desk.space_id.id,
                'desk_id': desk.id,
                'booking_date': selection['booking_date'],
                'start_time': start,
                'end_time': end,
            })
            booking.action_confirm()
            request.env.flush_all()
        except (ValidationError, UserError) as exc:
            request.env.cr.rollback()
            return fail(exc.args[0])
        except IntegrityError:
            request.env.cr.rollback()
            return fail(_("That desk was just booked by someone else. Please pick another one."))
        return request.redirect('/my/hot-desks/%s' % booking.id)

    # ------------------------------------------------------------------------------
    #   MARK: FLOOR PICKER DATA
    # ------------------------------------------------------------------------------
    @http.route(['/my/hot-desks/desks'], type='http', auth='user', methods=['GET'])
    def portal_hot_desk_desks(self, **kw):
        """Free desks for the asked contract and slot, the colleagues the
        desk may be for, and the floors drawing the centre's hot desks."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        selection = self._hot_desk_selection(kw)
        desks = selection['desks']
        return request.make_json_response({
            'desks': [self._hot_desk_option(d) for d in desks],
            'people': [{'id': p.id, 'name': p.name} for p in selection['people']],
            'sites': self._hot_desk_sites(selection['contract'], desks),
        })

    @http.route(['/my/hot-desks/floor/<int:plan_id>'], type='http', auth='user', methods=['GET'])
    def portal_hot_desk_floor(self, plan_id, contract_id=None, **kw):
        """The drawing of one floor of the contract's centre, read-only."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        plan = self._hot_desk_plan(plan_id, self._hot_desk_contract(contract_id))
        if not plan:
            return request.not_found()
        layout = request.env['workspace.floor.layout.service'].sudo()._load(plan)
        # Only the drawing: no palette, providers or edit rights in the portal.
        layout.update(presets=[], providers=[])
        layout['plan']['can_edit'] = False
        return request.make_json_response(layout)

    @http.route(['/my/hot-desks/floor/<int:plan_id>/slots'], type='http', auth='user', methods=['GET'])
    def portal_hot_desk_floor_slots(self, plan_id, **kw):
        """Free, booked or closed for each hot desk on the floor, for the
        asked contract and slot."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        selection = self._hot_desk_selection(kw)
        plan = self._hot_desk_plan(plan_id, selection['contract'])
        if not plan:
            return request.not_found()
        return request.make_json_response(self._hot_desk_slot_states(plan, selection))

    @http.route(['/my/hot-desks/desk/<int:desk_id>'], type='http', auth='user', methods=['GET'])
    def portal_hot_desk_details(self, desk_id, contract_id=None, **kw):
        """The side panel details of a hot desk of the contract's centre."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        contract = self._hot_desk_contract(contract_id)
        desk = request.env['business.center.desk'].sudo().browse(desk_id).exists()
        if not (contract and desk and desk.desk_type == 'hot'
                and desk.center_id == contract.center_id):
            return request.not_found()
        provider = request.env['workspace.floor.link.registry'].sudo()._get_provider(HOT_DESK_LINK_KEY)
        details = provider._fp_get_details(desk) or False
        if details:
            # The backend image URL needs read access on spaces: serve it here.
            space = desk.space_id
            details['image_url'] = '/my/hot-desks/photo/%s' % space.id if space.image_1920 else False
        return request.make_json_response(details)

    @http.route(['/my/hot-desks/photo/<int:space_id>'], type='http', auth='user', methods=['GET'])
    def portal_hot_desk_photo(self, space_id, **kw):
        """Photo of a coworking space in one of the member's centres."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        space = request.env['business.center.space'].sudo().browse(space_id).exists()
        if not (space and space.is_coworking
                and space.center_id in self._hot_desk_contracts().center_id):
            return request.not_found()
        return request.env['ir.binary']._get_image_stream_from(
            space, 'image_1920', width=480, height=360).get_response()