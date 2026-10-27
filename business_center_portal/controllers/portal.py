# -*- coding: utf-8 -*-
from odoo.addons.portal.controllers.portal import CustomerPortal


class BusinessCenterPortal(CustomerPortal):
    """Shared settings for every portal page added by this module.

    Anything that both contracts and bookings (and later invoices) need
    should live here, so it is written once instead of being repeated in
    each controller file.
    """

    # How many rows each portal list page shows before paging.
    _items_per_page = 8