# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


{
    'name': 'Business Center Portal',
    'version': '19.0.1.0.0',
    'category': 'Generic Modules',
    'sequence': 10,
    'author': 'Infintor Solutions',
    'price': 50,
    'currency': 'USD',
    'summary': 'Access coworking spaces, desks, and bookings through the member portal',
    'website': 'https://www.infintor.com',
    'depends': [
        'base', 'business_center', 'portal', 'account', 'sale'
    ],

    'images': ['static/description/banner.png'],

    'data': [

        'security/business_center_portal_groups.xml',
        'security/ir.model.access.csv',
        'security/business_center_portal_security.xml',
        
        'views/portal_invoice_templates.xml',
        'views/res_partner_views.xml',
        'views/portal_contract_templates.xml',
        'views/portal_booking_templates.xml',
        'views/portal_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'business_center_portal/static/src/scss/portal.scss',
            'business_center_portal/static/src/js/portal_booking.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'Other proprietary',
}
