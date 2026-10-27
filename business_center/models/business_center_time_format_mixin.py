# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class BusinessCenterTimeFormatMixin(models.AbstractModel):
    """Shared helpers for formatting float-hour values as readable time."""

    _name = 'business.center.time.format.mixin'
    _description = 'Time Formatting Helpers for Business Center'

    def _float_to_ampm(self, value):
        """Converts a float time value to a 12-hour AM/PM string.
           e.g. 13.5 -> '1:30 PM', 9.0 -> '9:00 AM'"""
           
        if value is None or value is False:
            return ''
        total = int(round(value * 60))
        hours, minutes = divmod(total, 60)
        period = 'AM' if hours % 24 < 12 else 'PM'
        display_hour = hours % 12 or 12
        return f"{display_hour}:{minutes:02d} {period}"
    
    def _float_to_duration(self, value):
        """Converts a float hour value to a readable duration.
           e.g. 0.8333 -> '50 min', 1.0 -> '1 hr', 2.5 -> '2 hrs 30 min'"""

        if not value:
            return '0 min'
        total = int(round(value * 60))
        hours, minutes = divmod(total, 60)
        if not hours:
            return f"{minutes} min"
        hour_label = 'hr' if hours == 1 else 'hrs'
        if not minutes:
            return f"{hours} {hour_label}"
        return f"{hours} {hour_label} {minutes} min"