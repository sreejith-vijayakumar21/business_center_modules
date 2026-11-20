# -*- coding: utf-8 -*-
# Copyright Infintor Solutions. License: Other proprietary (see 'license' below).


{
    'name': 'Business Center Tickets',
    'version': '19.0.1.1.0',
    'category': 'Generic Modules',
    'sequence': 11,
    'author': 'Infintor Solutions',
    'summary': 'Internet, facilities and maintenance tickets raised by members',
    'description': """
Support tickets for Business Center.

* Members raise internet, facilities and maintenance tickets from the portal, with photos.
* Each ticket is assigned automatically, by category and centre, and the assignee is notified.
* Staff and member talk on the ticket; the member is told when it is resolved and can reopen it.
* Response targets by priority, an overdue reminder, and resolution times for reporting.
""",
    'website': 'https://www.infintor.com',
    'depends': [
        'business_center_portal',
    ],

    'data': [
        'security/ir.model.access.csv',
        'security/business_center_ticket_security.xml',

        'data/ir_sequence_data.xml',
        'data/mail_activity_type_data.xml',
        'data/ticket_category_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',

        'views/business_center_ticket_views.xml',
        'views/business_center_ticket_category_views.xml',
        'views/res_config_settings_views.xml',
        'views/business_center_ticket_menus.xml',
        'views/portal_ticket_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'business_center_ticket/static/src/js/portal_ticket.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'Other proprietary',
}
