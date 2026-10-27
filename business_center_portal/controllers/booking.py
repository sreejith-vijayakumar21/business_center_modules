# -*- coding: utf-8 -*-

from collections import OrderedDict
from urllib.parse import urlencode

from psycopg2 import IntegrityError

from odoo import _, fields, http
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.http import request

import logging

_logger = logging.getLogger(__name__)


class BusinessCenterBookingPortal(CustomerPortal):
    """Everything the portal needs for showing meeting room bookings."""

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'booking_count' in counters:
            Booking = request.env['business.center.booking']
            values['booking_count'] = (
                Booking.sudo().search_count(self._get_bookings_domain())
                if Booking.has_access('read') else 0
            )
        return values

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
            #'upcoming': {'label': _('Upcoming'), 'domain': [('state', '=', 'upcoming')]},
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
        here explicitly because the portal now reads bookings with sudo(),
        so the account.move-style record rules no longer do the filtering.
        """
        user = request.env.user
        partner = user.partner_id.commercial_partner_id
        domain = [('contract_id.partner_id', 'child_of', partner.id)]
        if not user.has_group('business_center_portal.group_bc_tenant_admin'):
            domain.append(('user_id', '=', user.id))
        return domain
    
    def _bc_booking_access_denied(self):
        """Meeting-room booking is for Business Center tenants only.

        ``user.share`` is True for portal logins only, so an internal user
        browsing the portal is never blocked by this.
        """
        user = request.env.user
        if user.share and not user.has_group(
                'business_center_portal.group_bc_tenant_employee'):
            return request.redirect('/my')
        return False

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
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        searchbar_filters = self._booking_searchbar_filters()
        if not filterby:
            filterby = 'all'
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

    @http.route(['/my/bookings/<int:booking_id>'],
                type='http', auth='user', website=True)
    def portal_my_booking_detail(self, booking_id, access_token=None, **kw):
        """The detail page for one booking."""
        
        if not access_token:
            denied = self._bc_booking_access_denied()
            if denied:
                return denied
        try:
            booking_sudo = self._document_check_access(
                'business.center.booking', booking_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

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
    @staticmethod
    def _bc_today():
        """Today's date at the business centre, not the server's UTC date."""

        return request.env['business.center.booking'].sudo()._local_now().date()

    @staticmethod
    def _bc_to_int(value):
        """An id from the form or URL, or 0 if it was tampered with."""

        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

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
        if not user.has_group('business_center_portal.group_bc_tenant_admin') \
                and booking_sudo.user_id != user:
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
    def portal_booking_cancel(self, booking_id, access_token=None, **post):
        """Cancel one of the member's own bookings, releasing the slot and
        returning the wallet hours it drew."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        try:
            booking_sudo = self._document_check_access(
                'business.center.booking', booking_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

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
    #   MARK: BOOKING CREATION
    # ------------------------------------------------------------------
    def _member_contracts(self):
        """Contracts this member can book meeting rooms against.

        An employee is limited to contracts they are named on; a corporate
        admin may book against any of the company's contracts. Desk-only
        contracts are excluded - meeting-room booking rides on office space.
        """
        user = request.env.user
        partner = user.partner_id.commercial_partner_id
        domain = [
            ('partner_id', 'child_of', partner.id),
            ('state', '=', 'active'),
            ('is_wallet_eligible', '=', True),
        ]
        if not user.has_group('business_center_portal.group_bc_tenant_admin'):
            domain.append(('contact_ids', 'in', [user.partner_id.id]))
        return request.env['business.center.contract'].sudo().search(domain)

    def _rooms_for_center(self, center):
        """Bookable meeting rooms in the centre the contract's assets sit in."""

        Space = request.env['business.center.space'].sudo()
        if not center:
            return Space
        return Space.search([
            ('space_type', '=', 'meeting_room'),
            ('is_bookable', '=', True),
            ('center_id', '=', center.id),
            ('state', 'in', ('available', 'occupied')),
        ])

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

    @staticmethod
    def _hhmm_to_float(value, label):
        """Turn '09:30' from the form into the 9.5 float the model stores."""

        try:
            hours, minutes = value.split(':')
            result = int(hours) + int(minutes) / 60.0
        except (AttributeError, ValueError):
            raise UserError(_("Please pick a valid %s.") % label)
        if not 0.0 <= result <= 24.0:
            raise UserError(_("Please pick a valid %s.") % label)
        return result

    def _resolve_selection(self, contract_id, room_id, booking_date):
        """Pick the contract, room and date to show, falling back to the first
        available option. Ids are only used to look records up inside the
        member's own scope, never trusted as permission; malformed values fall
        back instead of raising."""

        contracts = self._member_contracts()
        contract = contracts.filtered(
            lambda c: c.id == self._bc_to_int(contract_id))[:1] or contracts[:1]
        rooms = self._rooms_for_center(contract.center_id)
        room = rooms.filtered(
            lambda r: r.id == self._bc_to_int(room_id))[:1] or rooms[:1]
        try:
            booking_date = fields.Date.to_string(
                fields.Date.to_date(booking_date)) if booking_date else False
        except ValueError:
            booking_date = False
        booking_date = booking_date or fields.Date.to_string(self._bc_today())
        return contracts, contract, rooms, room, booking_date

    def _booking_form_values(self, contract, contracts, rooms, room,
                             booking_date, **extra):
        """Everything the booking form template needs."""

        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'booking',
            'contracts': contracts,
            'contract': contract,
            'rooms': rooms,
            'room': room,
            'booking_date': booking_date,
            'wallet': contract.wallet_balance if contract.is_wallet_eligible else 0.0,
            'free_hours': contract.free_hours_monthly,
            'today': fields.Date.to_string(self._bc_today()),
            'slots_html': self._slots_html(room, booking_date),
            'error': '',
        })
        values.update(extra)
        return values

    @http.route(['/my/bookings/new'], type='http', auth='user',
                website=True, methods=['GET'])
    def portal_booking_new(self, contract_id=None, meeting_room_id=None,
                           booking_date=None, **kw):
        """The booking form."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        contracts, contract, rooms, room, booking_date = self._resolve_selection(
            contract_id, meeting_room_id, booking_date)
        if not contracts:
            return request.render(
                'business_center_portal.portal_booking_no_office',
                {'page_name': 'booking'})
        return request.render(
            'business_center_portal.portal_booking_form',
            self._booking_form_values(contract, contracts, rooms, room,
                                      booking_date))

    @http.route(['/my/bookings/slots'], type='http', auth='user',
                website=True, methods=['GET'])
    def portal_booking_slots(self, meeting_room_id=None, booking_date=None, **kw):
        """Return just the availability strip, so changing the room or date
        refreshes the colours without reloading the page."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        contracts, contract, rooms, room, booking_date = self._resolve_selection(
            kw.get('contract_id'), meeting_room_id, booking_date)
        return request.make_json_response({
            'slots': str(self._slots_html(room, booking_date) or ''),
            'hours': room.operating_hours_display or '',
            'rate': room.hourly_rate,
            'wallet': contract.wallet_balance if contract.is_wallet_eligible else 0.0,
            'rooms': [{'id': r.id, 'name': r.display_name} for r in rooms],
        })

    @http.route(['/my/bookings/new'], type='http', auth='user',
                website=True, methods=['POST'])
    def portal_booking_submit(self, **post):
        """Validate the submitted slot against the member's own contracts and
        create a confirmed booking. A draft would reserve nothing, so two
        members could claim the same slot."""

        denied = self._bc_booking_access_denied()
        if denied:
            return denied
        contracts, contract, rooms, room, booking_date = self._resolve_selection(
            post.get('contract_id'), post.get('meeting_room_id'),
            post.get('booking_date'))

        def fail(message):
            return request.render(
                'business_center_portal.portal_booking_form',
                self._booking_form_values(contract, contracts, rooms, room,
                                          booking_date, error=message))

        if not contract:
            return fail(_("Pick one of your running contracts."))
        if not room:
            return fail(_("Pick a meeting room in your business centre."))
        if fields.Date.from_string(booking_date) < self._bc_today():
            return fail(_("Bookings cannot be made for a past date."))

        try:
            start = self._hhmm_to_float(post.get('start_time'), _("start time"))
            end = self._hhmm_to_float(post.get('end_time'), _("end time"))
        except UserError as exc:
            return fail(exc.args[0])
        if end <= start:
            return fail(_("The end time must be after the start time."))

        Booking = request.env['business.center.booking'].sudo()
        try:
            booking = Booking.create({
                'contract_id': contract.id,
                'meeting_room_id': room.id,
                'booking_date': booking_date,
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