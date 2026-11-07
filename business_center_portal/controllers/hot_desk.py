# -*- coding: utf-8 -*-
from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal

ANSWERS = ('keep', 'release')


class HotDeskBookingPortal(CustomerPortal):
    """The page a customer reaches from the "still coming?" reminder.

    Opening the link only shows the question; the answer is applied when
    they press the button (POST), so email link scanners cannot release a
    desk by visiting the link.
    """

    @http.route(['/my/hot-desk/<int:booking_id>/<string:answer>'],
                type='http', auth='public', website=True, methods=['GET', 'POST'])
    def portal_hot_desk_answer(self, booking_id, answer, access_token=None, **kw):
        if answer not in ANSWERS:
            return request.not_found()
        try:
            booking = self._document_check_access(
                'business.center.desk.booking', booking_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        message = False
        if request.httprequest.method == 'POST':
            message = booking._bc_customer_answer(answer)
        return request.render('business_center_portal.portal_hot_desk_answer', {
            'booking': booking,
            'answer': answer,
            'access_token': access_token,
            'message': message,
        })
