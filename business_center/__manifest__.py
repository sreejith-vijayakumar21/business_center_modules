# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


{
    'name': 'Business Center',
    'version': '19.0.1.0.0',
    'category': 'Generic Modules',
    'sequence': 10,
    'author': 'Infintor Solutions',
    'price': 50,
    'currency': 'USD',
    'summary': 'Manage coworking spaces, desks, and member bookings',
    'description': 'Manages coworking spaces, desks, tenant contracts, meeting-room bookings and monthly billing.',
    'website': 'https://www.infintor.com',
    'depends': [
        'base', 'mail', 'account',
    ],

    'images': ['static/description/banner.png'],

    'data': [
        'security/business_center_groups.xml',
        'security/ir.model.access.csv',
        'security/business_center_security.xml',
        
        'data/mail_template_data.xml',
        'data/product_data.xml',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',

        'views/res_config_settings_views.xml',
        'views/business_center_booking_views.xml',
        'views/business_center_amenity_views.xml',
        'views/business_center_leased_asset_views.xml',
        'views/business_center_contract_charge_views.xml',
        'views/business_center_contract_views.xml',
        'views/business_center_desk_views.xml',
        'views/business_center_space_views.xml',
        'views/business_center_views.xml',
        'views/business_center_menus.xml'
    ],
    'installable': True,
    'application': True,
    'pre_init_hook': 'pre_init_hook',
    'post_init_hook': 'post_init_hook',
    'license': 'Other proprietary',
}
