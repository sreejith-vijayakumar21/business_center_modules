# Workspace Floor Planner (Odoo 19)

A standalone floor-plan designer for coworking spaces and business centers.
Staff draw each floor on a blank canvas, place private offices, dedicated
desks, hot desks, meeting rooms, coworking zones, walls, doors and amenities,
and (once a bridge addon is installed) see the live status of every rentable
unit, coloured and labelled.

* Depends only on `base` and `web`: installs in a clean Odoo 19 database.
* Never creates or copies business records (spaces, desks, bookings, contracts).
* Business integration lives in a separate, optional bridge addon.

---

## 1. Installation

1. Copy `workspace_floor_planner/` into a folder on your Odoo `addons_path`.
2. Restart Odoo, update the apps list, install **Workspace Floor Planner**.
3. Give users one of the groups under *Settings → Users → Floor Planner*:

| Group | Can do |
|---|---|
| Viewer | Open plans and see statuses (read-only editor). |
| Designer | Everything above + edit layouts, link units. |
| Administrator | Everything above + create / archive / delete plans, configure palette presets and status colours. |

The admin user gets *Administrator* automatically.

Upgrade: replace the folder and run `odoo-bin -u workspace_floor_planner -d <db>`.
Back up the database and try in staging first.

## 2. Using it

1. **Floor Planner → Floor Plans → New**: name, site/building, floor code,
   canvas size (logical units; default 50 units = 1 m), grid.
2. Click **Open Designer**.
3. Click a palette item to drop it in the middle of the view.
4. Drag to move, square handles to resize, round handle to rotate
   (15° steps; hold **Shift** for free rotation / to ignore the grid).
5. Edit label, exact position/size/rotation and colours in the right panel.
6. **Save** (or Ctrl+S). Reopening the plan shows exactly the same layout.

Keyboard: arrows nudge (Shift = one grid step), Del deletes, Ctrl+D
duplicates, Ctrl+Z / Ctrl+Y undo/redo, Esc deselects. Drag the empty floor to
pan, Ctrl + mouse wheel (or pinch) to zoom, **Fit** to see the whole floor.

**Live View** (button on the plan form) shows the totals (Total, Available,
Occupied, Maintenance) above a read-only, colour-coded layout. Click a unit
to see its status and open its record; **Edit layout** opens the designer.

Leaving the designer with unsaved changes asks *Save and leave / Discard*.
If someone else saved the same plan meanwhile, your save is refused with a
clear message instead of silently overwriting their work.

### Rentable units, zones and statuses

* Each private office, dedicated desk, hot desk and meeting room is its own
  object, linked to **its own** business record. A record can be placed only
  once per plan; duplicates start unlinked.
* A *Coworking Zone* is only a visual group. It summarises the units whose
  centre lies inside it ("3 of 8 available") and is *partial* when they
  differ. It is never a rentable unit itself.
* Walls, doors, windows, columns, amenities and labels are never rentable.
* Rentable objects are coloured by status, never by hand. Status is always
  written as text too (on the shape, in the tooltip and in the legend).

| Code | Default colour | Meaning |
|---|---|---|
| available | green | Nothing blocks the unit in the selected context. |
| occupied | red | In use now. |
| reserved | purple | A confirmed booking/contract blocks it. |
| maintenance | yellow | Out of service. |
| partial | blue | Zones only: mixed statuses inside. |
| unknown | light grey | Not linked, or status cannot be determined. |

Colours/labels are editable in *Configuration → Status Colours*; palette
items (sizes, colours, icons, new items such as "Phone booth") in
*Configuration → Palette Presets*.

**Refreshing statuses:** statuses are computed on the server on every
request, never stored. They refresh when the designer opens, after each save,
with the **Refresh** button, and automatically every *Status Refresh*
seconds if set on the plan (one batched request per refresh). If a bridge
says statuses depend on time, a date/time picker appears in the legend.

Without a bridge every rentable object shows *Not linked / unknown*, and
the panel explains that linking is not available. All drawing works.

## 3. Architecture

```
workspace_floor_planner/
  tools/constants.py        shared vocabulary: object types, categories, statuses, limits
  tools/geometry.py         pure geometry (rotation, point-in-rotated-rect)
  models/                   data only
    floor_plan.py           workspace.floor.plan  (+ thin, access-checked RPC entry points)
    floor_plan_object.py    workspace.floor.plan.object
    floor_status.py         workspace.floor.status (colour/label per status code)
    floor_object_preset.py  workspace.floor.object.preset (palette)
  services/                 behaviour, one responsibility each (AbstractModels)
    layout_validator.py     validates + normalises payloads and records, never writes
    layout_service.py       load / atomic save with optimistic locking
    status_service.py       asks providers for statuses, derives zone summaries
    link_registry.py        lists providers; validates links; names; open action
    link_provider.py        base "interface" every bridge provider inherits
  static/src/floor_planner/
    core/geometry.js        pure geometry (resize in rotated frame, fit, snap)
    core/layout_store.js    client state, undo/redo, serialisation
    core/floor_plan_api.js  the only code that talks to the server
    canvas/                 SVG canvas (gestures) + FloorObject (one shape)
    palette/ properties/ link_selector/ legend/ toolbar/   small UI components
    editor/                 client action that composes everything
```

How SOLID is applied:

* **Single responsibility** – models store data; validation, persistence,
  status and linking are separate services; on the client, state (store),
  transport (API) and each UI part are separate classes.
* **Open/closed** – new palette items and colours are data; new business
  record types are new provider classes registered by a bridge, without
  touching the core.
* **Liskov** – every provider can replace the base provider: same methods,
  same return shapes; "unknown" is always a valid answer.
* **Interface segregation** – a provider implements only what it needs
  (usually `_fp_get_statuses`); security plumbing is inherited.
* **Dependency inversion** – the core depends on the abstract provider
  contract, never on business models; UI components depend on the store/API
  objects they receive, not on the ORM.

### Geometry convention

Logical canvas units, independent of screen size and zoom. `x, y` is the
top-left corner of the **unrotated** rectangle; `rotation` is degrees
clockwise around the centre, stored in [0, 360). The unrotated rectangle
must lie inside the canvas; corners of a rotated shape may stick out a
little (deliberate, so rotating near a wall is never blocked). Minimum size
2 units, at most 2000 objects per plan.

### Bridge contract

A bridge adds providers:

```python
class DeskProvider(models.AbstractModel):
    _name = "workspace.floor.link.provider.desk"
    _inherit = "workspace.floor.link.provider"
    _description = "Floor link: desks"
    _fp_link_key = "desk"                      # stable, stored on objects
    _fp_link_label = "Hot Desk"
    _fp_target_model = "my_center.desk"
    _fp_object_types = frozenset({"hot_desk"})

    def _fp_get_statuses(self, records, at=None):
        # Use the business system's own logic, batched.
        return {desk.id: desk._my_status(at) for desk in records}

class Registry(models.AbstractModel):
    _inherit = "workspace.floor.link.registry"
    def _get_provider_models(self):
        return super()._get_provider_models() + ["workspace.floor.link.provider.desk"]
```

Optional overrides: `_fp_search_domain(plan)`, `_fp_is_time_dependent()`,
`_fp_target_domain()`, `_fp_get_open_action(record)`, and on the status
service `_plan_summary(plan, ...)` for the totals of the live view. The
`workspace_floor_planner_business_bridge` addon is the complete example for
the Business Center app.

## 4. Security

* ACLs per group (see table above); multi-company record rules on plans and
  objects (`company_id in company_ids + [False]`).
* All editor calls go through record methods that check read/write access
  first and then use the normal ORM as the current user (no `sudo`).
* Save payloads are validated completely before anything is written:
  allowed keys only, known object types, finite numbers, size/bounds,
  rotation, hex colours, icon class pattern, label length, object count,
  object ids must belong to the plan. The client can never send a status
  or a company.
* Links: the provider key must be registered, the object type allowed for
  that provider, the record must exist, be readable by the user and be in
  a compatible company. The same generic error is returned in all failure
  cases so record existence is not revealed. Names of records that become
  unreadable are shown as "Restricted or missing record".
* Opening a linked record re-checks all of the above on the server.
* Statuses from providers are filtered to known codes; anything else is
  shown as unknown.

Production hardening: keep users in the least-privileged group, test the
bridge's record rules with a non-admin user, and keep `--dev` off.

Uninstalling removes plans and objects (business records are untouched).

## 5. Tests

Python (validation, save/reload, access rights, companies, linking, zone
summaries, status filtering):

```
odoo-bin -d <test_db> -i workspace_floor_planner --test-tags=/workspace_floor_planner --stop-after-init
```

JavaScript unit tests (geometry and client store), Hoot runner:
open `/web/tests?filter=@workspace_floor_planner` while logged in.

Manual checks: see `TESTING.md`.

## 6. Known limitations

* No multi-select / group move yet (single object at a time).
* No free-form polygons: every shape is a (rotatable) rectangle; L-shaped
  rooms are drawn with two shapes.
* Zone membership is geometric (desk centre inside zone).
* Rotated shapes snap their position, not their edges, to the grid.
