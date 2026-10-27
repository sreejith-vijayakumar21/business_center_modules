# Business Center Modules

Odoo 19 modules for running a business centre: private offices, coworking
desks, meeting rooms, tenant contracts with security deposits and automatic
renewal, monthly billing, and a tenant-facing portal.

## Modules

| Module                   | Purpose | Sold separately |
|--------------------------|---------|-----------------|
| `business_center`        | Backend: centres, spaces, desks, contracts, renewals, bookings, billing, schedulers | Yes |
| `business_center_portal` | Tenant portal at `/my`: contracts, meeting-room bookings, invoice history | Requires `business_center` |

The backend works on its own. Installing the portal adds tenant self-service
on top, and uninstalling it returns the database to backend only.

Each module has its own README with details:

- [`business_center/README.md`](business_center/README.md) — roles, booking,
  billing and renewal rules, installation, per-client deployment checklist
- [`business_center_portal/README.md`](business_center_portal/README.md) —
  tenant roles and the changes it makes to stock `account` record rules

## Requirements

- Odoo 19.0 (Community or Enterprise)
- PostgreSQL with the `btree_gist` extension available — see
  `business_center/README.md`, Installation
- Odoo modules: `mail` and `account` for the backend; the portal also needs
  `portal` and `sale`
- No extra Python packages

## Installation

Add this repository folder (the one containing this README) to Odoo's
addons path, then install from Apps or the command line.

Backend only:

```bash
odoo-bin -d <database> \
  --addons-path=<odoo>/addons,<path>/business_center_modules \
  -i business_center
```

Backend and portal:

```bash
odoo-bin -d <database> \
  --addons-path=<odoo>/addons,<path>/business_center_modules \
  -i business_center,business_center_portal
```

On Odoo.sh, push this repository as-is; the modules are detected
automatically.

After installing, work through the deployment checklist in
`business_center/README.md`: company email, Business Center settings
(timezone, reminder lead days, renewal increase), outgoing and incoming
mail, `btree_gist` check, user roles, migrated contracts, taxes, payment
providers and the security deposit account.

## Upgrading

Upgrade the modules that are installed in the database:

```bash
odoo-bin -d <database> \
  --addons-path=<odoo>/addons,<path>/business_center_modules \
  -u business_center,business_center_portal --stop-after-init
```

For a backend-only database, use `-u business_center`. Check the output for
`ERROR` or `CRITICAL` lines before starting the server again.

## Module names

The technical names are `business_center` and `business_center_portal`.
Earlier internal builds used `bussiness_center` / `bussiness_center_portal`;
a database that has those installed cannot be upgraded in place to these
modules.

## Author and licence

Infintor Solutions — https://www.infintor.com
Licence: Other proprietary