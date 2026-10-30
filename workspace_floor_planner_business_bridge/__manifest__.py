{
    "name": "Business Center Floor Layouts",
    "summary": "Floors tab with live, colour-coded floor layouts for Business Center",
    "description": """
Connects Workspace Floor Planner to the Business Center app:

* Floors page of a business center shows floors as cards with available
  offices, desks and meeting rooms.
* First open of a floor creates its layout, pre-filled with the floor's
  offices, coworking desks and meeting rooms, ready to arrange.
* Afterwards the floor opens a live view: totals on top and the layout
  coloured by each unit's real status.
""",
    "version": "19.0.1.0.0",
    "category": "Services",
    "author": "Floor Layout Designer",
    "license": "LGPL-3",
    "depends": ["business_center", "workspace_floor_planner"],
    "data": [
        "security/floor_layout_security.xml",
        "views/business_center_floor_views.xml",
        "views/business_center_views.xml",
        "views/workspace_floor_plan_views.xml",
    ],
    "installable": True,
    "auto_install": True,
}
