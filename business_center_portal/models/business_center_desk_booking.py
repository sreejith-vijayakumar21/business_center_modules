# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class BusinessCenterDeskBooking(models.Model):
    """Hot desk bookings reachable from a token link, so a customer can
    answer the "still coming?" reminder without logging in."""

    _name = 'business.center.desk.booking'
    _inherit = ['business.center.desk.booking', 'portal.mixin']

    # ------------------------------------------------------------------------------
    #   MARK: COMPUTE/OVERRIDDEN METHODS
    # ------------------------------------------------------------------------------
    def _compute_access_url(self):
        """Portal address of the booking's answer page."""

        super()._compute_access_url()
        for rec in self:
            rec.access_url = '/my/hot-desk/%s' % rec.id

    def _bc_reminder_template(self):
        """Use the reminder with Keep / Release buttons."""

        return self.env.ref('business_center_portal.mail_template_hot_desk_reminder_portal',
                            raise_if_not_found=False) or super()._bc_reminder_template()

    def _bc_send_reminder(self):
        """Make sure each booking has an access token before its link is mailed."""

        for rec in self:
            rec._portal_ensure_token()
        return super()._bc_send_reminder()
