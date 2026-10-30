# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


{
    'name': 'Workspace Floor Planner',
    'version': '19.0.1.0.0',
    'category': 'Services',
    'sequence': 10,
    'author': 'Infintor Solutions',
    'price': 50,
    'currency': 'USD',
    'summary': 'Visually design business-center floors: offices, desks, meeting rooms and amenities',
    'description': """
Standalone floor-plan designer for coworking spaces and business centers.

* Draw floors on a blank canvas: private offices, hot desks, dedicated desks,
  meeting rooms, coworking zones, walls, doors and amenities.
* Move, rotate, resize, style, duplicate and delete objects, then save.
* Rentable objects show a server-computed status colour (with text + legend).
* Business integration is pluggable: a separate bridge addon registers
  "link providers" that map objects to existing business records.
""",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [
        
        "security/floor_planner_groups.xml",
        "security/ir.model.access.csv",
        "security/floor_planner_rules.xml",
        
        "data/floor_status_data.xml",
        "data/floor_object_preset_data.xml",
        
        "views/floor_plan_views.xml",
        "views/floor_status_views.xml",
        "views/floor_object_preset_views.xml",
        "views/floor_planner_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "workspace_floor_planner/static/src/floor_planner/**/*",
        ],
        "web.assets_unit_tests": [
            "workspace_floor_planner/static/tests/**/*.test.js",
        ],
    },
    "application": True,
    "installable": True,
}
