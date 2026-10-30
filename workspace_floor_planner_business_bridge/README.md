# Business Center Floor Layouts (bridge)

Connects **Workspace Floor Planner** to the **Business Center** app
(`business_center`). It installs automatically when both are installed.

## What you get

1. **Business Center → a center → Floors tab** now shows each floor as a card:
   available / total offices, desks and meeting rooms, and whether the floor
   already has a layout.
2. **Create layout** (first time): the floor's layout is created and the
   designer opens, already filled with every private office, each coworking
   space as a zone with its desks inside, and every meeting room, each linked
   to its record. Drag them into their real position, add walls, doors and
   amenities, then save.
3. **View layout** (afterwards): the live view opens with the totals on top
   (Total spaces, Available, Occupied, Maintenance, plus Reserved when there
   is one) and the layout below, coloured by real status: green available,
   red occupied, yellow maintenance, purple reserved. Click a unit to see its
   status and open its record. **Edit layout** goes back to the designer.

Nothing is copied or created in Business Center: offices, desks, rooms,
contracts and bookings stay the source of truth.

## Model mapping

| Floor object | Business Center model | Records offered | Status source | Mapping | Click-through |
|---|---|---|---|---|---|
| Private Office | `business.center.space` | `space_type = office`, not coworking, same floor | `state` | available→available, occupied→occupied, maintenance→maintenance, draft→unknown | space form |
| Dedicated / Hot Desk | `business.center.desk` | desks of coworking spaces on the same floor | `state` | same as above | desk form |
| Meeting Room | `business.center.space` | `space_type = meeting_room`, same floor | `state`, then confirmed `business.center.booking` for the chosen date/time | maintenance/draft as above; booking running now → occupied; later the same day → reserved; else available | space form |
| Coworking Zone | (visual only) | – | derived from the desks inside | "x of y available" | – |

Meeting-room status depends on time, so the live view shows a date/time
picker; bookings use the user's time zone, like the booking form.

Floor totals count **all** units of the floor (also the ones not placed on
the drawing yet; the view says how many are missing).

## Rights

| Business Center group | Floor Planner rights it gets |
|---|---|
| User | Viewer: see floors and live layouts |
| Manager | Administrator: create and edit layouts |

A floor without a layout can only be set up by someone with Floor Planner
administrator rights; others get a clear message.

## Refresh

Statuses are read live on every open, after every save, with **Refresh**,
and automatically if *Status Refresh (seconds)* is set on the floor plan.
A contract, booking or state change shows on the next refresh.

## Technical notes

* `services/link_providers.py` – the three providers (one class each) and
  `workspace.floor.bc.units`, the single place that decides which records are
  a floor's units.
* `services/status_service.py` – floor totals.
* `services/layout_generator.py` – starting layout (sizes from `area_sqm`
  when filled in, 50 units = 1 m).
* `models/` – `bc_floor_id` on the plan (one layout per floor) and the floor
  card counts / actions.
* Tests: `odoo-bin -d <db> -i business_center,workspace_floor_planner --test-tags=/workspace_floor_planner_business_bridge --stop-after-init`

Note: `business_center` has no record rules on floors, spaces and desks, so
multi-company isolation for those relies on your own setup; the floor
planner still checks read access and company on every linked record.
