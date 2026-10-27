# Business Center

Manages coworking spaces, private offices, desks, tenant contracts,
security deposits, meeting-room bookings, monthly billing and contract
renewal.

## Structure

Centre → floor → space → desk. A space is either an office or a meeting room;
an office flagged as coworking exposes a desk matrix instead of being leased
whole. Space references are numbered per centre (e.g. `BC01/F0/OS0001`).

A desk can only be made available once its coworking space is available.
Putting a space under maintenance moves its available desks with it; occupied
desks stay with their tenants. A coworking space follows its desks: it is
Occupied once no desk can be leased, and Available again when one frees up.

Contracts link a tenant to specific offices and desks over a date range.
Confirming a contract claims occupancy on those assets; expiry releases them.

## Roles

- **User** — read centres, spaces and desks; create and confirm bookings;
  draft contracts. Users see contracts but not their invoices.
- **Manager** — everything a User can, plus configuration, space and desk
  status, contract confirmation, cancellation, renewal and invoicing,
  deposit settlement, past-dated bookings and booking reset.

Manager-only actions are enforced in the model, not only hidden in the views.

## Bookings

- Booking times are local to the business centre: they are compared in the
  timezone set under Settings, then the user's.
- Only managers can confirm a booking whose start time has passed (for
  recording usage that was never entered).
- A confirmed booking cannot be cancelled once its session has started.
  Managers can correct mistakes with Reset to Draft, which refunds the wallet.
- Overlapping bookings of the same room are refused by a database constraint
  (see Installation), so two simultaneous confirmations cannot both succeed.

## Billing

Rent is agreed per leased asset: it starts from the space or desk's list
rent and can be negotiated while the contract is draft. Once the contract is
confirmed the rent is locked, and changing a space's list rent later does
not affect existing contracts.

Billing cycles are aligned to the calendar month. A contract starting
mid-month is billed for the remainder of that month only, prorated on days
over days-in-month, so every cycle after the first opens on the 1st.

Meeting-room overage is billed as one line per room for the exact accrued
amount, with the duration in the label (e.g. "Meeting Room - BC02/F2/MS0003
(50 min)").

**Migrated contracts:** confirming a contract that started before the current
month requires Next Invoice Date to be set to the first period not yet
billed. Otherwise the billing scheduler would invoice every month since the
start date again.

Six scheduled actions run daily at 01:00 UTC, in priority order:

- 10 — Activate upcoming contracts
- 20 — Generate monthly invoices
- 30 — Reset free-hour wallets
- 35 — Renew contracts
- 40 — Expire contracts and prepare deposit refunds
- 50 — Send expiry reminders

Invoices are created as drafts and posted by hand after review.

## Security deposit

Each contract holds one refundable deposit, entered while the contract is
draft and locked once it is confirmed.

- **On confirmation** a separate, tax-free draft invoice is raised for the
  deposit, using the Security Deposit product. Rent is never mixed into it.
- **On expiry or cancellation** a draft credit note is prepared for the
  deposit the tenant actually paid, and the contract's creator gets a
  "Settle security deposit" activity. If the deposit invoice was never paid,
  it is cancelled instead and no refund is prepared.
- **On renewal** the deposit carries over to the successor; only an increase
  is invoiced, as a top-up. The final refund covers everything paid across
  the renewals.
- **Settling** — post the refund for the full deposit, invoice damages or
  other deductions separately, apply the refund's credit to the tenant's
  unpaid invoices, then pay out the balance. This keeps income, tax and the
  deposit liability correct.

## Free-hour wallet

A contract leasing at least one office carries a monthly meeting-room hour
allowance. The balance resets on the 1st of each month with no carry-forward.
Booking beyond the balance raises a charge that is swept onto the next invoice.

## Expiry reminders and renewal

Reminders are emailed from the company, using the company's email address,
and posted on the contract's chatter. A company without an email address
cannot send them; the button reports this and the scheduler logs it.

The reminder is due the given number of lead days before the end date, but
never before the contract starts. For a contract shorter than the lead time,
the form reduces the lead days to the contract's length, so the reminder
goes out on the start date.

A contract marked **Auto Renew** is renewed the day after it ends, before the
expiry scheduler runs: a successor contract is created and confirmed for the
same term length, with the same assets, employees, free hours and deposit,
so its spaces never become available. Each asset's rent is raised by the
contract's **Renewal Rent Increase (%)**, which new contracts take from the
company default in Settings; use 0 to renew at the same rent. The two
contracts are linked (Renewed From / Renewed As).

Managers can also renew a running or expired contract with **Renew**, which
creates a draft successor to review. A renewal keeps the same spaces and
desks; only rent and deposit can be adjusted. Moves and changes in size are
new contracts. If an automatic renewal fails (for example the space was let
to someone else), a note is posted on the contract and it expires normally.

## Installation

The booking table uses a PostgreSQL `EXCLUDE USING gist` constraint to prevent
double-booking, which needs the `btree_gist` extension. `pre_init_hook`
creates it, but that hook runs on install only — **on an existing database,
run this as a superuser before installing:**

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
```

If the extension cannot be created, installation continues without the
constraint and overlapping bookings become possible at the database layer.
Verify after every deployment:

```sql
SELECT extname FROM pg_extension WHERE extname = 'btree_gist';
SELECT conname FROM pg_constraint WHERE conrelid = 'business_center_booking'::regclass AND contype = 'x';
```

Both queries must return a row.

## Deployment checklist

Per client database, after installing:

1. **Company email** — Settings > Companies. Reminders are sent from it.
2. **Business Center settings** — Business Center > Configuration > Settings:
   timezone (e.g. `Asia/Kolkata`, used by booking time checks), reminder
   lead days and default renewal rent increase.
3. **Outgoing mail** — Odoo.sh / Odoo Online include a mail server; on-premise,
   add an outgoing server for the client's provider and set SPF/DKIM on
   their domain.
4. **Replies** — configure an alias domain and incoming mail if tenant replies
   to reminders should reach the contract chatter; otherwise adjust the
   reminder template's wording.
5. **`btree_gist`** — run the verification queries above.
6. **Roles** — assign staff the Business Center User or Manager role.
7. **Migrated contracts** — set Next Invoice Date before confirming.
8. **Taxes** — install the client's accounting localization (e.g. India,
   UAE), then set Customer Taxes on the Office Rent, Desk Rent and Meeting
   Room Hire products. Invoices take their tax from these products.
9. **Tenant payments** — Invoicing > Configuration > Payment Providers:
   enable an online provider or Wire Transfer with the client's bank
   details, and publish it, so the portal's Pay Now button has a payment
   method.
10. **Security deposits** — set the Security Deposit product's income
    account to the client's liability account for customer deposits, with
    no taxes, so deposits are not booked as revenue.

## Related

`business_center_portal` adds the tenant-facing portal. See its README — it
narrows two stock `account` record rules, which matters on a shared database.