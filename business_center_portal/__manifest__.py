# -*- coding: utf-8 -*-
# Copyright Infintor Solutions. License: Other proprietary (see 'license' below).


{
    'name': 'Business Center Portal',
    'version': '19.0.1.2.0',
    'category': 'Generic Modules',
    'sequence': 10,
    'author': 'Infintor Solutions',
    'price': 50,
    'currency': 'USD',
    'summary': 'Access coworking spaces, desks, and bookings through the member portal',
    'description': """
Tenant portal for Business Center.

* Corporate admins see their company's contracts, signed agreements and invoices.
* Tenants book meeting rooms against their contract.
* Tenants book hot desks for themselves or a colleague, on a floor plan or a list.
""",
    'website': 'https://www.infintor.com',
    'depends': [
        'business_center', 'portal', 'account', 'sale',
        'workspace_floor_planner_business_bridge'
    ],

    'images': ['static/description/banner.png'],

    'data': [

        'security/business_center_portal_groups.xml',
        'security/ir.model.access.csv',
        'security/business_center_portal_security.xml',
        
        'data/hot_desk_mail_data.xml',
        
        'views/portal_hot_desk_booking_templates.xml',
        'views/portal_hot_desk_templates.xml',
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
            # Read-only floor canvas and details panel, shared with the backend picker.
            'workspace_floor_planner/static/src/floor_planner/floor_planner.scss',
            'workspace_floor_planner/static/src/floor_planner/core/geometry.js',
            'workspace_floor_planner/static/src/floor_planner/core/layout_store.js',
            'workspace_floor_planner/static/src/floor_planner/canvas/*',
            'workspace_floor_planner/static/src/floor_planner/picker/floor_unit_details.*',
            'workspace_floor_planner/static/src/floor_planner/picker/pickability.js',
            # Hot desk booking form and its floor picker.
            'business_center_portal/static/src/js/hot_desk_events.js',
            'business_center_portal/static/src/js/portal_hot_desk.js',
            'business_center_portal/static/src/hot_desk_picker/*',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'Other proprietary',
    'uninstall_hook': 'uninstall_hook',
}
