# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import OrderedDict
from urllib.parse import urlencode

from psycopg2 import IntegrityError

from odoo import _, fields, http
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.http import request

from odoo.addons.portal.controllers.portal import pager as portal_pager

from .portal import BusinessCenterPortal

MEETING_ROOM_LINK_KEY = 'bc_meeting_room'


class BusinessCenterBookingPortal(BusinessCenterPortal):
    """Everything the portal needs for meeting room bookings: list, detail,
    cancel, the booking form and the data its floor picker reads.

    The tenant check, the date, time and id parsing and the floor picker
    helpers come from BusinessCenterPortal, shared with the hot desk pages.
    Availability is the booking model's (_bc_free_rooms, _slot_held), so the
    plan, the dropdown and the confirmation always agree.
    """

    # ------------------------------------------------------------------
    #   MARK: HOME COUNTER
    # ------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'booking_count' in counters:
            Booking = request.env['business.center.booking']
            values['booking_count'] = (
                Booking.sudo().search_count(self._get_bookings_domain())
                if Booking.has_access('read') else 0
            )
        return values

    # ------------------------------------------------------------------
    #   MARK: LIST AND DETAIL
    # ------------------------------------------------------------------
    def _booking_searchbar_sortings(self):
        """The choices in the 'Sort By' dropdown on the booking list."""
        return {
            'date': {'label': _('Date'), 'order': 'booking_date desc, start_time desc'},
            'name': {'label': _('Reference'), 'order': 'name desc'},
            'room': {'label': _('Meeting Room'), 'order': 'meeting_room_id'},
            'state': {'label': _('Status'), 'order': 'state'},
        }

    def _booking_searchbar_filters(self):
        """The choices in the 'Filter By' dropdown on the booking list."""
        return {
            'all': {'label': _('All'), 'domain': []},
            'draft': {'label': _('Draft'), 'domain': [('state', '=', 'draft')]},
            'confirmed': {'label': _('Confirmed'), 'domain': [('state', '=', 'confirmed')]},
            'cancelled': {'label': _('Cancelled'), 'domain': [('state', '=', 'cancelled')]},
        }

    def _booking_searchbar_inputs(self):
        """The choices in the search box dropdown ('Search in ...')."""
        return {
            'name':     {'input': 'name',     'label': _('Search in Reference')},
            'room':     {'input': 'room',     'label': _('Search in Meeting Room')},
            'contract': {'input': 'contract', 'label': _('Search in Contract')},
            'all':      {'input': 'all',      'label': _('Search in All')},
        }

    def _get_booking_search_domain(self, search_in, search):
        """Turn what the member typed into a filter, based on the field
        they chose to search in."""

        if search_in == 'name':
            return [('name', 'ilike', search)]
        if search_in == 'room':
            return [('meeting_room_id.name', 'ilike', search)]
        if search_in == 'contract':
            return [('contract_id.name', 'ilike', search)]
        return ['|', '|',
                ('name', 'ilike', search),
                ('meeting_room_id.name', 'ilike', search),
                ('contract_id.name', 'ilike', search)]

    def _get_bookings_domain(self):
        """Bookings this member may see. An employee only sees their own; a
        corporate admin sees everything on the company's contracts. Stated
        here explicitly because the portal reads bookings with sudo(), so
        the record rules no longer do the filtering.
        """
        user = request.env.user
        partner = user.partner_id.commercial_partner_id
        domain = [('contract_id.partner_id', 'child_of', partner.id)]
        if not self._bc_is_tenant_admin():
            domain.append(('user_id', '=', user.id))
        return domain

    @http.route(['/my/bookings', '/my/bookings/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_bookings(self, page=1, sortby=None, filterby=None,
                           search=None, search_in='all', **kw):
        """The list page showing all bookings of the logged-in member."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        Booking = request.env['business.center.booking'].sudo()
        domain = self._get_bookings_domain()

        searchbar_sortings = self._booking_searchbar_sortings()
        # An unknown value from the URL falls back instead of raising KeyError.
        sortby = sortby if sortby in searchbar_sortings else 'date'
        order = searchbar_sortings[sortby]['order']

        searchbar_filters = self._booking_searchbar_filters()
        filterby = filterby if filterby in searchbar_filters else 'all'
        domain += searchbar_filters[filterby]['domain']

        searchbar_inputs = self._booking_searchbar_inputs()
        if search and search_in:
            domain += self._get_booking_search_domain(search_in, search)

        booking_count = Booking.search_count(domain)
        pager = portal_pager(
            url='/my/bookings',
            url_args={'sortby': sortby, 'filterby': filterby,
                      'search': search, 'search_in': search_in},
            total=booking_count,
            page=page,
            step=self._items_per_page,
        )
        bookings = Booking.search(
            domain, order=order, limit=self._items_per_page, offset=pager['offset'])
        request.session['my_bookings_history'] = bookings.ids[:100]

        values = self._prepare_portal_layout_values()
        values.update({
            'bookings': bookings,
            'page_name': 'booking',
            'pager': pager,
            'default_url': '/my/bookings',
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
            'searchbar_filters': OrderedDict(sorted(searchbar_filters.items())),
            'filterby': filterby,
            'searchbar_inputs': searchbar_inputs,
            'search_in': search_in,
            'search': search,
        })
        return request.render('business_center_portal.portal_my_bookings', values)

    def _bc_get_booking_sudo(self, booking_id):
        """Return (booking_sudo, None) when the member may see the booking,
        else (None, redirect response). Shared by the detail and cancel pages."""

        denied = self._bc_booking_access_denied()
        if denied:
            return None, denied
        try:
            return self._document_check_access('business.center.booking', booking_id), None
        except (AccessError, MissingError):
            return None, request.redirect('/my')

    @http.route(['/my/bookings/<int:booking_id>'],
                type='http', auth='user', website=True)
    def portal_my_booking_detail(self, booking_id, **kw):
        """The detail page for one booking."""

        booking_sudo, redirect = self._bc_get_booking_sudo(booking_id)
        if redirect:
            return redirect

        values = {
            'booking': booking_sudo,
            'page_name': 'booking',
            'can_cancel': self._can_cancel_booking(booking_sudo),
            'cancel_block_reason': self._booking_cancel_block_reason(booking_sudo),
            'error': kw.get('error', ''),
        }
        return request.render('business_center_portal.portal_booking_page', values)

    # ------------------------------------------------------------------
    #   MARK: BOOKING CANCELLATION
    # ------------------------------------------------------------------
    def _booking_cancel_block_reason(self, booking_sudo):
        """Why this member may not cancel this booking, or False if they may.
        An employee can only undo what they booked themselves; a corporate admin
        can undo anything on the company's contracts. A slot that has already
        started, or whose overage is already on an invoice, is the centre's to
        reverse."""

        user = request.env.user
        if booking_sudo.state == 'cancelled':
            return _("This booking has already been cancelled.")
        if booking_sudo.state != 'confirmed':
            return _("Only a confirmed booking can be cancelled.")
        if not self._bc_is_tenant_admin() and booking_sudo.user_id != user:
            return _("Only the person who made this booking, or your company's "
                     "administrator, can cancel it.")
        if booking_sudo._is_in_past():
            return _("This slot has already started and can no longer be cancelled.")
        invoiced = booking_sudo.contract_id.charge_ids.filtered(
            lambda c: c.booking_id == booking_sudo and c.state == 'invoiced')
        if invoiced:
            return _("This booking's extra charge has already been invoiced. "
                     "Please contact the business centre.")
        return False

    def _can_cancel_booking(self, booking_sudo):
        """Whether this member may cancel this booking."""

        return not self._booking_cancel_block_reason(booking_sudo)

    @http.route(['/my/bookings/<int:booking_id>/cancel'], type='http',
                auth='user', website=True, methods=['POST'])
    def portal_booking_cancel(self, booking_id, **post):
        """Cancel one of the member's own bookings, releasing the slot and
        returning the wallet hours it drew."""

        booking_sudo, redirect = self._bc_get_booking_sudo(booking_id)
        if redirect:
            return redirect

        reason = self._booking_cancel_block_reason(booking_sudo)
        if reason:
            return request.redirect('/my/bookings/%s?%s' % (
                booking_id, urlencode({'error': reason})))

        try:
            booking_sudo.action_cancel()
            request.env.flush_all()
        except (UserError, ValidationError) as exc:
            request.env.cr.rollback()
            return request.redirect('/my/bookings/%s?%s' % (
                booking_id, urlencode({'error': exc.args[0]})))

        return request.redirect('/my/bookings/%s' % booking_id)

    # ------------------------------------------------------------------
    #   MARK: SCOPE HELPERS
    # ------------------------------------------------------------------
    def _member_contracts(self):
        """Contracts this member can book meeting rooms against.

        An employee is limited to contracts they are named on; a corporate
        admin may book against any of the company's contracts. Desk-only
        contracts are excluded - meeting-room booking rides on office space.
        """
        return self._bc_member_contracts([('is_wallet_eligible', '=', True)])

    def _member_contract(self, contract_id):
        """One of the member's contracts, or an empty recordset."""

        return self._member_contracts().filtered(
            lambda c: c.id == self._bc_to_int(contract_id))[:1]

    @staticmethod
    def _center_rooms(center):
        """Every meeting room of the centre, open for booking or not."""

        Space = request.env['business.center.space'].sudo()
        if not center:
            return Space
        return Space.search([('space_type', '=', 'meeting_room'), ('center_id', '=', center.id)])

    def _rooms_for_center(self, center):
        """Bookable meeting rooms in the centre the contract's assets sit in."""

        return self._center_rooms(center).filtered(
            lambda r: r.is_bookable and r.state in ('available', 'occupied'))

    @staticmethod
    def _room_fits(room, attendees):
        """Whether ``room`` seats ``attendees``; a room without a capacity
        set is not ruled out."""

        return not (attendees and room.capacity and room.capacity < attendees)

    def _slots_html(self, room, booking_date):
        """Render the day's availability strip by reusing the model's own compute,
        so the portal and the backend always show the same thing."""

        if not (room and booking_date):
            return False
        preview = request.env['business.center.booking'].sudo().new({
            'meeting_room_id': room.id,
            'booking_date': fields.Date.to_date(booking_date),
        })
        return preview.slot_availability_html

    def _resolve_selection(self, values):
        """Contract, date, times, attendees, rooms and the free ones, from
        what was posted or asked. Ids are only used to look records up inside
        the member's own scope, never trusted as permission; malformed values
        fall back instead of raising."""

        contracts = self._member_contracts()
        contract = contracts.filtered(
            lambda c: c.id == self._bc_to_int(values.get('contract_id')))[:1] or contracts[:1]
        rooms = self._rooms_for_center(contract.center_id)
        booking_date = self._bc_parse_date(values.get('booking_date')) or self._bc_today()
        start = self._bc_parse_time(values.get('start_time'))
        end = self._bc_parse_time(values.get('end_time'))
        attendees = max(self._bc_to_int(values.get('attendees')), 0)
        free = request.env['business.center.booking'].sudo()._bc_free_rooms(
            rooms, booking_date, start or 0.0, end or 0.0)
        fitting = free.filtered(lambda r: self._room_fits(r, attendees))
        room_id = self._bc_to_int(values.get('meeting_room_id'))
        room = rooms.filtered(lambda r: r.id == room_id)[:1] or fitting[:1] or rooms[:1]
        return {
            'contracts': contracts,
            'contract': contract,
            'rooms': rooms,
            'free': fitting.sorted('name'),
            'room': room,
            'booking_date': booking_date,
            'start': start,
            'end': end,
            'attendees': attendees,
        }

    @staticmethod
    def _room_option(room):
        """A room as the form's dropdown and the picker show it."""

        return {
            'id': room.id,
            'name': room.display_name,
            'rate': room.hourly_rate,
            'hours': room.operating_hours_display or '',
        }

    def _room_slot_states(self, plan, selection):
        """'free', 'booked', 'closed' or 'small' for every meeting room drawn
        on ``plan``, keyed by shape id, for the chosen slot and group size."""

        center_rooms = self._center_rooms(selection['contract'].center_id)
        held = request.env['business.center.booking'].sudo()._slot_held(
            center_rooms, selection['booking_date'], selection['start'] or 0.0, selection['end'] or 0.0)
        rooms = {room.id: room for room in center_rooms}
        free_ids, held_ids = set(selection['free'].ids), set(held.ids)
        bookable_ids = set(selection['rooms'].ids)

        def state_of(room_id):
            room = rooms.get(room_id)
            if not room:
                return None
            if room_id in free_ids:
                return 'free'
            if room_id in held_ids:
                return 'booked'
            if room_id in bookable_ids and not self._room_fits(room, selection['attendees']):
                return 'small'
            return 'closed'

        return self._bc_floor_slot_states(plan, MEETING_ROOM_LINK_KEY, state_of)

    # ------------------------------------------------------------------
    #   MARK: BOOKING FORM
    # ------------------------------------------------------------------
    def _booking_form_values(self, selection, **extra):
        """Everything the booking form template needs."""

        contract, room = selection['contract'], selection['room']
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'booking',
            'contracts': selection['contracts'],
            'contract': contract,
            'room': room,
            'room_options': [self._room_option(r) for r in selection['free']],
            'room_id': room.id if room in selection['free'] else 0,
            'booking_date': fields.Date.to_string(selection['booking_date']),
            'start_hhmm': self._bc_float_to_hhmm(selection['start']),
            'end_hhmm': self._bc_float_to_hhmm(selection['end']),
            'attendees': selection['attendees'] or '',
            'wallet': contract.wallet_balance if contract.is_wallet_eligible else 0.0,
            'free_hours': contract.free_hours_monthly,
            'today': fields.Date.to_string(self._bc_today()),
            'slots_html': self._slots_html(room, selection['booking_date']),
            'error': '',
        })
        values.update(extra)
        return values

    @http.route(['/my/bookings/new'], type='http', auth='user',
                website=True, methods=['GET'])
    def portal_booking_new(self, **kw):
        """The booking form."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        selection = self._resolve_selection(kw)
        if not selection['contracts']:
            return request.render(
                'business_center_portal.portal_booking_no_office',
                {'page_name': 'booking'})
        return request.render('business_center_portal.portal_booking_form',
                              self._booking_form_values(selection))

    @http.route(['/my/bookings/new'], type='http', auth='user',
                website=True, methods=['POST'])
    def portal_booking_submit(self, **post):
        """Validate the submitted slot against the member's own contracts and
        create a confirmed booking. A draft would reserve nothing, so two
        members could claim the same slot."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        selection = self._resolve_selection(post)
        contract, room = selection['contract'], selection['room']
        posted_room = self._bc_to_int(post.get('meeting_room_id'))

        def fail(message):
            return request.render('business_center_portal.portal_booking_form',
                                  self._booking_form_values(selection, error=message))

        if not contract:
            return fail(_("Pick one of your running contracts."))
        if not (room and room.id == posted_room):
            return fail(_("Pick a meeting room in your business centre."))
        if selection['booking_date'] < self._bc_today():
            return fail(_("Bookings cannot be made for a past date."))
        start, end = selection['start'], selection['end']
        if start is None or end is None:
            return fail(_("Pick a start and an end time."))
        if end <= start:
            return fail(_("The end time must be after the start time."))
        if not self._room_fits(room, selection['attendees']):
            return fail(_("%(room)s seats %(seats)s; your group is %(people)s. Please pick a larger room.",
                          room=room.name, seats=room.capacity, people=selection['attendees']))

        Booking = request.env['business.center.booking'].sudo()
        try:
            booking = Booking.create({
                'contract_id': contract.id,
                'meeting_room_id': room.id,
                'booking_date': selection['booking_date'],
                'start_time': start,
                'end_time': end,
                'user_id': request.env.user.id,
            })
            booking.action_confirm()
            request.env.flush_all()
        except (ValidationError, UserError) as exc:
            request.env.cr.rollback()
            return fail(exc.args[0])
        except IntegrityError:
            request.env.cr.rollback()
            return fail(_("That slot was just taken by someone else. "
                          "Please pick another time."))

        return request.redirect('/my/bookings/%s' % booking.id)

    # ------------------------------------------------------------------
    #   MARK: FORM AND FLOOR PICKER DATA
    # ------------------------------------------------------------------
    @http.route(['/my/bookings/rooms'], type='http', auth='user', methods=['GET'])
    def portal_booking_rooms(self, **kw):
        """Free rooms for the asked contract, slot and group size, the
        contract's wallet, and the floors drawing the centre's rooms."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        selection = self._resolve_selection(kw)
        contract = selection['contract']
        return request.make_json_response({
            'rooms': [self._room_option(r) for r in selection['free']],
            'wallet': contract.wallet_balance if contract.is_wallet_eligible else 0.0,
            'sites': self._bc_floor_sites(MEETING_ROOM_LINK_KEY, contract.center_id,
                                          self._center_rooms(contract.center_id), selection['free']),
        })

    @http.route(['/my/bookings/slots'], type='http', auth='user',
                website=True, methods=['GET'])
    def portal_booking_slots(self, **kw):
        """The picked room's availability strip for the day, so changing the
        room or the date refreshes it without reloading the page."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        selection = self._resolve_selection(kw)
        room = selection['room']
        return request.make_json_response({
            'slots': str(self._slots_html(room, selection['booking_date']) or ''),
            'hours': room.operating_hours_display or '',
            'rate': room.hourly_rate,
        })

    @http.route(['/my/bookings/floor/<int:plan_id>'], type='http', auth='user', methods=['GET'])
    def portal_booking_floor(self, plan_id, contract_id=None, **kw):
        """The drawing of one floor of the contract's centre, read-only."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        contract = self._member_contract(contract_id)
        plan = self._bc_floor_plan(plan_id, contract.center_id)
        if not plan:
            return request.not_found()
        return request.make_json_response(self._bc_floor_layout(plan))

    @http.route(['/my/bookings/floor/<int:plan_id>/slots'], type='http', auth='user', methods=['GET'])
    def portal_booking_floor_slots(self, plan_id, **kw):
        """Free, booked, closed or too small for each meeting room on the
        floor, for the asked contract, slot and group size."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        selection = self._resolve_selection(kw)
        plan = self._bc_floor_plan(plan_id, selection['contract'].center_id)
        if not plan:
            return request.not_found()
        return request.make_json_response(self._room_slot_states(plan, selection))

    @http.route(['/my/bookings/room/<int:room_id>'], type='http', auth='user', methods=['GET'])
    def portal_booking_room_details(self, room_id, contract_id=None, **kw):
        """The side panel details of a meeting room of the contract's centre."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        contract = self._member_contract(contract_id)
        room = self._center_rooms(contract.center_id).filtered(lambda r: r.id == room_id)
        if not room:
            return request.not_found()
        image_url = '/my/bookings/room/%s/photo' % room.id if room.image_1920 else False
        return request.make_json_response(self._bc_unit_details(MEETING_ROOM_LINK_KEY, room, image_url))

    @http.route(['/my/bookings/room/<int:room_id>/photo'], type='http', auth='user', methods=['GET'])
    def portal_booking_room_photo(self, room_id, **kw):
        """Photo of a meeting room in one of the member's centres."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        centers = self._member_contracts().center_id
        room = request.env['business.center.space'].sudo().browse(room_id).exists()
        if not (room and room.space_type == 'meeting_room' and room.center_id in centers):
            return request.not_found()
        return self._bc_image_response(room)
