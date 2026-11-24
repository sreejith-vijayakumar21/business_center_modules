# -*- coding: utf-8 -*-
# Copyright Infintor Solutions. License: Other proprietary (see 'license' below).


{
    'name': 'Business Center Community',
    'version': '19.0.1.1.0',
    'category': 'Generic Modules',
    'sequence': 12,
    'author': 'Infintor Solutions',
    'price': 50,
    'currency': 'USD',
    'summary': 'Community feed of announcements, updates and member photos',
    'description': """
Community feed for Business Center.

* Staff publish announcements and updates for one business center or all of them.
* Members share updates and photos from the portal; staff approve them first (optional).
* Members comment on posts; important announcements are emailed to the members concerned.
""",
    'website': 'https://www.infintor.com',
    'depends': [
        'business_center_portal',
    ],

    'data': [
        'security/ir.model.access.csv',
        'security/business_center_community_security.xml',

        'data/mail_activity_type_data.xml',
        'data/mail_template_data.xml',

        'views/business_center_post_views.xml',
        'views/res_config_settings_views.xml',
        'views/business_center_community_menus.xml',
        'views/portal_community_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'Other proprietary',
}
