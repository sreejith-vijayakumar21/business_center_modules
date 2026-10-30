# Test plan and evidence

## What was run (Odoo 19.0 community, Python 3.13, PostgreSQL 16)

| Check | Result |
|---|---|
| Install in a clean database (only `base`, `web` + deps) | OK, no warnings |
| Upgrade (`-u workspace_floor_planner`) | OK |
| Uninstall | OK, tables removed |
| Python tests (`--test-tags=/workspace_floor_planner`) | 25 / 25 pass |
| JS unit tests (Hoot, `/web/tests?filter=@workspace_floor_planner`) | 12 / 12 pass |
| Browser run-through (headless Chromium, details below) | OK, no console errors |
| With `business_center`: fresh install of both (bridge auto-installs), core + bridge tests | 34 / 34 pass (11 bridge tests incl. real bookings) |
| Business Center browser run: Floors tab cards → Create layout (pre-filled, 14 objects) → save → View layout (totals 12 / 4 / 6 / 2 match the records) | OK, no console errors |

Browser run-through, done against a running Odoo 19 server with a small
test-only provider that maps partners to statuses:

* Create a plan, open the designer: blank canvas with grid and legend.
* Add a coworking zone, 4 hot desks, an office, a wall, a door, a rotated
  meeting room, a canteen and a text label; edit labels and X/Y/size via the
  panel; drag to move, drag handles to resize and rotate.
* Link each desk to its own record and the office to another; save with
  Ctrl+S; statuses appear in colour and text; zone shows "2 of 4 available".
* Reload: every object's position, size and rotation is identical.
* Ctrl+D on a linked desk creates an unlinked copy; Ctrl+Z removes it.
* Leaving with unsaved changes shows *Save and leave / Discard*; Discard leaves.
* "Open" on a linked office opens its form.
* Viewer user: editor is read-only (no Save, palette disabled, dragging
  does not move objects).
* Two sessions edit the same plan: the second save is refused with the
  "changed by someone else" message.
* 400-desk plan: opens in ~1.2 s; dragging stays smooth (one shape
  re-renders per pointer move). Server: save 400 objects 0.15 s, load 0.08 s,
  status 0.02 s.

Not verified here: Odoo Enterprise, your real production data, touch
devices, browsers other than Chromium.

## Manual checklist for your staging server

1. Install, then log in as a user with only *Floor Planner / Designer*.
2. Create two plans as an Administrator; check the Designer cannot create or
   delete plans but can edit their layouts.
3. Draw a floor using every palette group; rotate a shape to 45°, resize it
   from a corner, then reload the page and compare.
4. Try to drag an object past the canvas edge: it stops at the edge.
5. Zoom with Ctrl + wheel, pan by dragging the empty floor, click **Fit**.
6. Toggle Grid and Snap; hold Shift while dragging to place freely.
7. Delete a zone (asks for confirmation), undo, redo.
8. In a second browser, save the same plan, then save in the first: a clear
   conflict error must appear and nothing is overwritten.
9. Log in as a Viewer: everything visible, nothing editable.
10. Multi-company: a plan of company B is invisible to a user of company A.
11. After the bridge is installed: link desks, check statuses against the
    business center, create/cancel a booking, press **Refresh** and confirm
    the colour changes; check a user without access to a unit cannot open it.
