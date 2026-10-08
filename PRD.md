# Loan Management System — Product Requirements Document (PRD)

Version 7.0 — whole shillings, rounded up, never short the lender
(§3.3/§4): every loan-schedule interest/instalment figure is now computed
in whole shillings, rounded UP only (never down), with the instalment
additionally rounded up to the loan's own stored rounding step (default
1,000, CEO/Head Manager configurable, never retroactive). All other money
amounts system-wide (repayments, penalties, expenses, assets, capital,
payroll, settlement, discounts) are now whole-shilling inputs, rejected
outright if fractional — interest RATES are the one exception and keep
decimals. Also this version: (2) a loan product locks its rate only,
never its term (a real bug fix — term used to be force-set to the
product's default); renamed "no product" to "Negotiated rate" (§3.4);
(3) due dates now show in every on-screen schedule, and the calculator
takes its own start date (§3.3); (4) early settlement gained an optional,
reason-required interest discount restricted to Loans Manager/Head
Manager/CEO (§3.5a); (5) the Payslips button's dead-on-arrival download
is fixed, and payroll deductions are now itemized via a configurable
deduction-types table — no rate hard-coded in code (§3.8); (6) the Users/
Employees account lists use small text status labels and text-link row
actions instead of large coloured pills and buttons, the "ID verification
not configured" message is gone (the whole feature is hidden until a
provider is actually configured), and a failed form submission now shows
as a floating toast AND scrolls to/highlights the first invalid field
(§4). A dedicated baseline-vs-after simulation of five partial/late-
payment scenarios was run before and after this pass specifically to
separate rounding-driven differences from anything else — one genuine
non-rounding bug was found and fixed this way: a schedule row
settled by more than one partial payment was only ever showing its LAST
payment's interest/principal, silently dropping the earlier payment's
contribution from the row (and therefore from the totals row). Where this
version conflicts with anything earlier, this version wins.

Previous: Version 6.0 — a correctness/usability pass on top of v5.0, in priority
order: (1) **critical** — a paid schedule row must display the real
repayment split (from the Repayment record), never the stale originally-
scheduled figures, so the totals row always reconciles to the loan's
original principal (§3.5); (2) borrowers get NO approval step, confirmed
again as a hard rule after a second regression (§3.2); (3) borrower photo/
ID uploads accept PDF and are fully optional at creation (§3.2); (4) a
Loans Manager (Department Manager, `loans_credit`) can create/edit Loan
Products, a loan's product is now optional (a negotiated/custom loan), and
a selected product's rate/term are locked server-side (§3.4); (5)
repayments can be started from the Repayments page or the loan's own page
through one shared function, loan references are always a full clickable
link, and payment-received confirmation is emailed (§3.5); (6) the
department field on a Checker/Maker's own create/edit form is shown but
disabled, since department no longer affects what they can do (§2); (7)
editing a user is a self-contained modal, not inline (§3.12); (8) pending-
approval lists auto-refresh on focus/interval and a stale decide attempt
names who already handled it and when (§3.10); (9) every tier can submit
their own leave request, and an HR/Head Manager/CEO reviewer can edit the
requested dates before approving (§3.8); (10)-(11) employee form layout
and the Create-login action are fixed (§3.12a); (12) status messages are a
floating toast, not a fixed banner (§4); (13) the Users table scrolls
within its own card and a pending user's actions stay visible (§3.12);
(14) monetary rounding is audited for consistent 2dp quantization with
residual rounding absorbed in the final period (§4). Early settlement/
prepayment calculation is explicitly UNCHANGED in this version — on hold
pending a separate client decision. Where this version conflicts with
anything earlier, this version wins.

## 1. Purpose

Replace the client's previous loan management software, retired due to
critical calculation errors: interest calculated on original principal
rather than outstanding balance, and portfolio figures that didn't
reflect true exposure. This document is the single source of truth for
what the system must do — module scope, roles, and rules — so future
development (by any tool or person) builds against one coherent spec
instead of ad hoc patches.

## 2. Roles and Permissions

Five tiers, each an account's `role` column, plus a `department` column
(`hr`, `finance`, `loans_credit`, or `general` — required for the three
scoped tiers below, always null for the two unscoped ones). There is
**nothing else to configure per user** — the earlier per-account
permission-matrix checkboxes and their backing table are retired
entirely. What an account can do is derived purely from its tier and,
for the scoped tiers, its department, computed by the one function
`services/permissions.py`'s `has_permission(user, permission)`.

1. **CEO** — untouchable by anyone else, including another CEO if one
   ever exists: cannot be deactivated, deleted, or have their role
   changed by anyone but themself, and cannot change their own role.
   Full access to every module, unconditionally. Only the CEO may
   create or remove a Head Manager.
2. **Head Manager** — full access across every department, unscoped.
   Can create/remove Department Manager, Checker and Maker accounts in
   any department. Cannot create or remove another Head Manager.
   Cannot touch a CEO account in any way. Can only be created or
   removed by the CEO.
3. **Department Manager** — scoped to exactly one of `hr`, `finance`,
   or `loans_credit` (never `general` — a Department Manager is always
   department-specific). Full access — every action, including both
   create and approve — within that department's own modules only
   (the mapping below). Can create and manage Checker and Maker
   accounts within their own department only; cannot create any kind
   of manager. Displayed with a derived title, never the raw
   role+department pair: "HR Manager", "Finance Manager", "Loans
   Manager" (not "Loans Credit Manager"). Can only be created or
   removed by the CEO or a Head Manager.
4. **Checker** — a fixed action set, **the same everywhere regardless of
   department** (simplified from an earlier, department-scoped design):
   can create borrowers, repayments, expenses, penalties, and their own
   leave request, and can **approve ANY loan**, with no department
   restriction whatsoever. **HARD RULES, no exception:** a Checker can
   never create a loan, and can never approve a leave request under any
   circumstance — leave approval belongs to Department Manager (HR),
   Head Manager, or CEO only. A Checker never approves a penalty either
   (unchanged: that stays Department Manager and above). Can be
   created/removed by the CEO, a Head Manager, or their own
   department's Manager (department is still required on the account
   for this purpose and for reporting, but no longer gates anything
   `has_permission()` decides).
5. **Maker** — a fixed action set, also with no department restriction:
   can create borrowers, loans, repayments, expenses, penalties, and
   their own leave request. **HARD RULE, no exception:** a Maker can
   never approve anything. Can be created/removed by the CEO, a Head
   Manager, or their own department's Manager.

**Department field on a Checker/Maker's own account form:** since
department plays no part in what either tier can do (points 4/5 above),
their own create/edit form still shows the department selector — it is
still stored and still useful for staff-listing/reporting purposes — but
it is **greyed out/disabled**, never required for them to change. A
Department Manager's own create/edit form keeps the selector fully
active and required, since their department is what scopes their access.

**Department → module mapping** (still the source of truth for
Department Manager, Head Manager and CEO — department plays NO part any
more in what a Checker or Maker can do; see point 4/5 above):

| Department | Modules |
|---|---|
| `hr` | employees, payroll, leave_requests |
| `finance` | expenses, capital, assets, reports |
| `loans_credit` | borrowers, loans, loan_products, repayments, penalties, calculator |
| `general` | all of the above — the unscoped tiers' natural reach, and a deliberate broad-access choice for a Department Manager who needs it (though a Department Manager should normally be `hr`/`finance`/`loans_credit` specifically) |

A Checker or Maker never reaches reports, assets, employees, payroll,
capital, or any admin-only capability (`users:manage`, `audit:view`,
`backup:manage`) — those are Department Manager (within their own
department) and above only. This is now simply because those actions
are not on either tier's fixed action set at all, not because of a
department check.

**Maker-checker stays narrowed to loans and penalties only.** Expenses,
payroll, assets, capital and employees are recorded/finalized directly
by whoever holds the matching module access — no second-person
approval. Leave requests are a simple request → approve/reject by
anyone whose department reaches the leave module (Department Manager
(HR), Head Manager, or CEO — never a Checker or a Maker, who both stay
request-only for their own leave), not maker-checker — they may decide
a request they filed themselves or on someone else's behalf.

**Self-approval, for loans and penalties only:**
`created_by` can never equal `approved_by` for a Checker or a Maker —
no exceptions. **CEO, Head Manager and Department Manager are exempt**
from this one rule: they may approve a loan or penalty they created
themselves. **There is no self-approved badge, flag, or audit
distinction of any kind** for this — a deliberate reversal of an
earlier decision. The approval is recorded exactly like any other; a
Department Manager holds full trusted authority within their own
department, so their self-approval needs no special marking.

**User–Employee link — one explicit choice, not a checkbox default:**
creating a Head Manager, Department Manager, Checker or Maker account
presents a radio choice: "Create new employee record" (default), "Link
to existing employee" (a dropdown of employees who have no login yet),
or "No employee record." Symmetrically, an employee with no login gets
a "Create login" action (prefilled with their email, sends the
verification email) and a "Link to User" action for an existing,
unlinked login.

**Permission tier vs. job title — kept separate, never merged:**
The five tiers above are the *only* thing that controls access — create
vs. approve, self-approval blocking, everything maker-checker depends
on. A real-world job title (Loan Officer, Accountant, Teller, HR
Officer, Cashier, or free text for anything else) is a separate field
on the **Employee** record, purely descriptive — it appears on
payslips, staff listings, and the Loan Officer Performance report, but
never itself grants or restricts any action. When creating/linking a
user, two independent choices are made: the tier (functional) and the
job title (descriptive). A sensible default may be suggested (Loan
Officer → Maker, Accountant → Checker) but is always overridable — the
two fields never move together automatically after the initial
suggestion.

## 3. Core Modules

### 3.1 Authentication
- Login by **email**, not phone.
- New user created by whoever the creation hierarchy permits (CEO, Head
  Manager, or a Department Manager within their own department) →
  verification email sent → user sets their own password via the link
  → account activated.
- **The verification/reset page is a public, token-only page.** It must
  never read or depend on any currently active session in the browser
  (fixes: verification opening into the CEO's dashboard instead of the
  set-password form). It must also **validate the token with the server
  before rendering the set-password form at all** — a missing, malformed,
  expired, or already-used token shows a clear "this link isn't valid"
  state with a "send me a new one" option, never the password form itself.
  A token is single-use: once consumed it (and any other outstanding link
  for the same account) stops validating immediately.
- **The session token lives in `sessionStorage`, never `localStorage`.**
  localStorage is shared by every tab of the same origin — a session there
  bleeds across tabs (a login in one tab silently changes what another tab
  shows). sessionStorage is per-tab by design, which is the actual
  requirement: each browser tab is its own independent session.
- Creating a user must never touch or invalidate the creating user's own
  session — their token keeps working, unaffected, for the rest of their
  session.
- Distinct, accurate error messages:
  - Wrong password → "Incorrect email or password."
  - Unverified email → "Please verify your email before logging in."
  - Actual expired session → "Your session expired. Please sign in again."
  These three cases must never be confused with one another.
- A `403 Forbidden` (wrong role) must **never** trigger logout. Only a
  genuine `401 Unauthorized` (expired/invalid token) triggers logout.
  A 403 shows an in-place "You don't have permission for this" message.

### 3.2 Borrowers
- **No approval step, ever — a hard rule.** A borrower is a plain record
  from the moment it is created: no `status`, no pending/approved state,
  nothing to wait on. It is listed and usable for a new loan immediately.
  This has regressed twice now (both times as a purely cosmetic status
  badge implying an approval state that never existed server-side) — any
  future change that makes a borrower look "pending" or "not yet
  approved" anywhere in the UI is a bug, full stop.
- Fields: name, phone, email (optional), **id_type** (nida,
  driving_licence, voter_id, passport, other — default nida) +
  **id_number**, address, photo (optional, image or PDF), id document
  (optional, image or PDF), risk notes, active/blacklist flag. **Both
  uploads are fully optional at creation time** — a borrower can be saved
  with neither and have them added later from their own detail page; a
  real-world ID is very often a scanned PDF rather than a photo, so PDF is
  accepted alongside JPEG/PNG/WebP for both fields, validated by content
  (magic bytes / `pypdf` parse / Pillow decode), never by the client's
  filename or declared Content-Type.
- A NIDA number is normalized (dashes/spaces stripped) before storage.
  If it is not 20 digits, a **soft warning** is shown — it is never
  blocked, because the real format has not been confirmed against
  physical cards yet.
- An exact duplicate (same id_type + id_number) is blocked with a link
  straight to the existing borrower's record, instead of a bare error.
- **ID verification** is a seam, not a working integration:
  `services/identity_verification.py`'s `verify_nin()` always reports
  `not_configured` today. **No unofficial NIDA scraper is used, and the
  whole verification UI (status row, "Verify ID" button) is hidden
  entirely while no provider is configured** — never a permanent "not
  configured" message sitting on every borrower's page. A real, licensed
  provider plugs into this same function later (flip
  `PROVIDER_CONFIGURED` to `True`) without touching any caller, and the
  UI reappears automatically.

### 3.3 Loan Calculator — Integrated, Not Standalone

**Amortization method — corrected to standard EMI (equal monthly
installment):** The monthly *payment amount stays constant* across the
loan's term; what changes each period is the split between principal
and interest (more interest early, more principal later). This is the
standard bank/microfinance method — NOT equal-fixed-principal-portions
with a shrinking payment, which was an earlier, incorrect assumption.

Formula, for a monthly rate `r` (annual rate ÷ 12) and `n` remaining
periods on outstanding balance `P`:
```
EMI = P × r × (1+r)^n / ((1+r)^n − 1)
```
**Rate convention — corrected to monthly, not annual:** The client
quotes and thinks in **monthly** interest rates (e.g. "10%" or "15%"
meaning per month), not annual rates. The `interest_rate` field is
therefore the **monthly rate applied directly** in the EMI formula —
`r` in the formula below is the entered rate as-is, with NO division
by 12. This was confirmed by the client's own workaround on a
third-party annual-rate-labeled calculator: she multiplies her real
monthly rate by 12 before entering it, specifically to counteract that
tool's internal ÷12 step and recover her true monthly figure. All
UI labels must say "Monthly Interest Rate (%)" — never "Annual
Interest Rate" — throughout the calculator, loan creation, loan
products, schedules, and reports, to prevent this exact confusion from
recurring.

**Whole shillings, rounded UP, never short the lender (confirmed,
superseding the earlier provisional cents-based figures below):**
1. Each row's interest = outstanding balance × monthly rate, rounded
   **UP** to the next whole shilling — the rounding only ever removes
   cents, it never changes how interest is calculated.
2. The instalment is the exact (unrounded) EMI, computed once on the
   original balance/term, rounded **UP** to the next multiple of the
   loan's own **rounding step** (a whole number, default 1,000 — a step
   of 1 just means "next whole shilling"). The same instalment repeats
   for every row except where it's clamped below.
3. A row's payment can never exceed that row's own remaining balance
   plus its own interest for that row — whichever row that happens on
   (the natural final period, or an earlier period when a small loan's
   balance no longer reaches the rounded-up instalment) closes the loan
   out exactly there; the schedule ends at that row and shows the
   actual number of instalments it took, never padded out with trailing
   zero rows.
4. Every computed principal, payment or balance is clamped at zero —
   never negative, and zero always displays as "0," never "-0."
5. After any repayment, the remaining schedule is recalculated by
   running the SAME function on the new outstanding balance and
   remaining periods, using the loan's own stored rounding step — one
   calculation path only, same as before.

**Instalment rounding step** is a Company Setting (CEO/Head Manager
only, a positive whole number, default 1,000). It is copied onto each
loan **at creation time** and stored there — changing the company
default later never alters an already-created loan's own step or its
already-generated schedule. The step is shown on the loan's own detail
page.

Reference (default step 1,000), 1,000,000 principal, 12 months: at 10%
monthly → instalment 147,000/month, row 1 principal 47,000 and interest
100,000, row 12 (final) payment 141,944, total interest 758,944, total
paid 1,758,944. At 15% monthly → instalment 185,000/month, row 12
payment 169,950, total interest 1,204,950, total paid 2,204,950.

All money amounts elsewhere in the system (repayments, penalties,
expenses, asset values, capital entries, salaries, payroll lines,
deductions, settlement, discounts) are **whole-shilling inputs** —
entering a fractional amount is rejected outright ("Enter an amount in
whole shillings.") rather than rounded, since those are direct entries,
not computed figures. **Interest rates are the one exception and may
keep decimals** (e.g. 10.5).

Totals are always the exact sum of the (already whole-shilling) rows —
no further rounding decision to make there; total principal across
every row always reconciles exactly to the loan's original principal.

**Separately closed decision — amortization method is EMI/reducing
balance, not flat rate.** The client initially described her method as
"flat rate," but running an identical test case through her own
reference calculator (thecalculatorsite.com) produced a result
matching this system's EMI implementation, not the much higher total a
true flat-rate calculation would produce, and the client separately
confirmed in writing that she uses reducing balance. "Flat rate" was
used colloquially to mean "the monthly payment is fixed," which EMI
already provides. This part of the design does not change — only the
rate input convention (monthly vs annual) above was still being
resolved.

- The calculator is **not a separate page users visit before creating a
  loan.** It is embedded directly in the loan creation form: as the
  Maker enters principal / rate / term, a live amortization schedule
  preview renders on the same screen, before submission.
- A separate standalone calculator page may still exist for quoting
  prospective borrowers who don't have a loan yet — but loan creation
  itself must never require leaving the page to "calculate first." It
  takes its own **start date** (defaulting to today).
- **Every on-screen schedule — calculator, loan-creation preview, and
  loan detail — shows a due-date column.** One consistent date format
  throughout.
- Both paths call the exact same underlying calculation function —
  never two separate implementations.
- **Flexible reconciliation, corrected:** when an early, late, partial,
  or extra repayment changes the outstanding balance mid-term, the
  remaining schedule is recalculated by running the SAME EMI formula
  again on the new outstanding balance over the remaining term — this
  naturally produces a new EMI for the remaining periods. The
  philosophy (schedule = plan, repayments = reality, balance always
  derived from reality) is unchanged; only the formula it runs on is
  corrected.

### 3.4 Loans
- Created by whoever holds `loans:create` — a Maker, a Department
  Manager whose department covers loans, a Head Manager, or the CEO.
  Never a Checker (hard rule, no exception). Status: `draft →
  pending_approval → active → closed / rejected`.
- **Loan Products are manageable by a Loans Manager too.** Creating/
  editing a `LoanProduct` is `loan_products:manage` — CEO, Head Manager,
  or a Department Manager scoped to `loans_credit` (a "Loans Manager").
  This was previously CEO/Head Manager only, which left the one role
  actually responsible for the loan book unable to maintain its own
  products.
- **A loan's product is optional — "Negotiated rate."** A Maker (or
  anyone with `loans:create`) may leave `loan_product_id` unset — shown
  as the "Negotiated rate" option, not "No product" — and enter
  principal, monthly interest rate, and term directly for a one-off
  negotiated loan. This runs through the exact same `loan_calculator.py`
  amortization function as a product-backed loan — nothing forks. When
  no product is selected, the "Product" column elsewhere in the UI
  reads "Negotiated rate," never a blank dash.
- **A selected product locks ONLY its interest rate — never the term.**
  The term is always entered per loan, same as a negotiated-rate loan,
  and is enforced **server-side**: whatever rate the client request
  sends alongside a `loan_product_id` is ignored outright in favor of
  the product's own rate. This is a real bug fix — term used to be
  force-set to the product's `default_term_months`, with no way to pick
  anything else. If the product has an optional min/max term (or min/max
  amount), those apply only as **validation bounds**, both client- and
  server-side — never a fixed value.
- On creation (before approval), the generated schedule is visible
  immediately on the loan's own page — not hidden until after approval.
- On approval, the schedule is delivered to the borrower: emailed if an
  email is on file, and/or exportable as PDF, and/or sendable via
  WhatsApp.
- Loans list shows a clearly separated "Pending my approval" section
  inline, not only inside the general Approvals queue.
- **Every reference to a loan by number (e.g. "#5"), anywhere in the
  UI,** is a single clickable link to that loan's detail page covering
  the whole identifier — never just the "#" character linked with the
  number as plain trailing text.
- Every amortization table (calculator, loan creation, loan detail
  page, schedule PDF) shows **only a bold totals row** below the last
  instalment (total principal, total interest, total payment) —
  computed server-side from the same schedule rows, current after any
  repayments. No separate summary line (e.g. a standalone monthly-
  payment/EMI figure) is shown above the table.

### 3.5 Repayments
- Can be started from **either** the general Repayments page (pick the
  loan first, then record against it) **or** the loan's own detail page
  — both entry points call the exact same underlying recording logic
  (one shared `RepaymentForm`/endpoint), never two parallel
  implementations that could drift apart.
- Interest allocated before principal on each repayment.
- Reducing-balance recalculation on every repayment: schedule = plan,
  repayments = reality, balance always derived from reality.
- **Repayment rules:** each period's interest is always computed fresh
  from the loan's ACTUAL outstanding principal at the moment of payment
  (balance x monthly rate, rounded up) — never read from a possibly-stale
  stored value (this also closes a real gap: a penalty directly adjusts
  `outstanding_balance` without rebuilding the schedule, so without this
  a later repayment's interest could be computed against a stale
  pre-penalty balance). A row only closes (status `paid`) once a payment
  covers what is CURRENTLY due on it in full (interest, then principal) —
  e.g. 120,000 paid against a 147,000 instalment leaves the row
  `partial`, shown as "Partially paid" with `original_expected_amount`
  (the instalment as originally scheduled, never overwritten) and the
  real interest/principal paid so far. Later periods are re-amortized on
  the ASSUMPTION the shortfall gets topped up by the row's own due date
  (a projection, not yet final) — top it up before the due date and the
  row simply closes, the projection confirmed unchanged. If the due date
  passes with the shortfall still unpaid,
  `carry_over_overdue_partial_periods()` (called by the same daily job as
  the missed-period delay below, reusing the same calculator function)
  gives up on the projection: the row is locked in at what was actually
  received (status `paid`, flagged `paid_less_than_scheduled` for the UI
  only), and the real remaining balance is re-amortized over the real
  remaining periods instead.
- **A period counts as missed only when its due date has passed with NO
  payment at all against it** (never automatically, never a penalty).
  Missing a period delays the WHOLE remaining schedule by one month —
  every unpaid due date, including the missed one, moves one month
  later; balance, instalment amounts and total interest are untouched.
  `original_due_date` (set once, never overwritten) and a
  `delayed_months` counter are kept per schedule row so the Portfolio at
  Risk report and overdue lists still correctly show who is actually
  behind, even though the live due date has been pushed back to
  accommodate them.
- **CRITICAL — a paid schedule row must display the REAL repayment, never
  the stale originally-scheduled figures.** The instant a schedule row's
  status becomes `paid`, its displayed principal/interest/payment are
  overwritten with the actual split from that Repayment record — this
  matters most when the amount paid is *larger* than what was scheduled
  for that instalment (the extra also lands on that row as real principal
  paid). Without this, a row that settled for more than its original
  instalment kept showing the smaller, stale scheduled principal while the
  balance had already been reduced by the real, larger amount — silently
  **under-counting** total principal across the schedule. The totals row
  must always equal "sum of the actual paid amounts (from repayment
  records) + sum of the currently recalculated remaining rows," and total
  principal across every row must always reconcile exactly to the loan's
  original principal. **Found and fixed via the baseline simulation:**
  a row settled by more than one
  partial payment was only showing its LAST payment's interest/principal —
  the earlier partial payment's own contribution was silently dropped from
  the row (and therefore from the totals row). A "paid" row now shows the
  CUMULATIVE interest/principal across every repayment ever applied to it.
  **Phase 3:** re-confirmed and re-fixed — a line immediately AFTER the
  correct cumulative calculation was silently overwriting it with just
  the latest payment's own amount, re-introducing the exact bug this
  section already describes as fixed. The loan detail page's repayment
  schedule now also shows three clearly labeled totals above the table:
  "Total of schedule" (`total_payable`), "Paid to date", and "Still to
  pay" (`total_payable` − `paid_to_date`).
- **Reject any repayment amount ≤ 0** at the API level, not just the
  frontend — this is a money-integrity rule, not a UI nicety. Every
  repayment amount is also a **whole shilling** (§4) — a fractional
  amount is rejected, not rounded.
- A payment-received confirmation is sent to the borrower by email
  (`payment_received` template, async) whenever a repayment is recorded
  and an email is on file, alongside whatever other delivery channel is
  already wired for it.

### 3.5a Early Settlement
- The rule itself is unchanged: settlement = outstanding principal + the
  full interest due on the currently-open instalment.
- **An optional interest discount** may be applied by a Loans Manager
  (Department Manager, `loans_credit`), Head Manager, or CEO only — never
  a Maker or Checker. It cannot be negative and cannot exceed that
  period's interest, requires a reason, and is written to the audit
  trail. The breakdown (principal, interest, discount, total to settle)
  is shown before confirming.
- If a typed repayment amount exceeds the settlement amount, the message
  is "The most you can pay today to settle this loan is X." — not a
  generic "amount too large" error.

### 3.6 Penalties
- Created by a Maker or a Checker, pending until a Department Manager,
  Head Manager, or CEO approves it — penalty *approval* is not a
  Checker action under the tier model (a real change from the previous
  design), unlike loan approval, which a Checker still holds.
- Approved penalty adds to outstanding balance.
- **Penalty Reversal.** A separate action (Department Manager and
  above only, same as approval) to reverse an already-approved
  penalty, requiring a reason, fully logged in the audit trail.
  Approved penalties are never silently edited or deleted — only
  reversed with a paper trail.

### 3.7 Capital Module (dedicated page)
- **Opening capital is a one-time setup**: cash amount + as-of date, no
  reason field the first time. Once set, the setup control disappears
  and the Capital page shows history instead. **Correcting** the
  opening figure afterward is **CEO-only**, requires a reason, and
  keeps the previous value in history — never overwritten.
- **Injections and withdrawals**: amount, date, note. `capital:manage`
  — CEO, Head Manager, or a Finance Department Manager — no approval step.
- **Cash on hand** = opening + injections − withdrawals + repayments
  received − loan principal disbursed − recorded expenses − finalized
  payroll. The Capital page shows cash on hand and **two clearly
  separate, explicitly labelled loan figures**, never conflated:
  **"Outstanding Balance"** (the live sum of each active loan's real
  outstanding balance — the figure used everywhere else, e.g. the
  reducing-balance math) and **"Total Disbursed"** (the lifetime sum of
  original principal across every loan ever created, active or closed
  — never itself used in the reducing-balance calculations). Also
  shown: assets value and total worth (cash + Outstanding Balance +
  assets), plus a "how this is calculated" panel with the live numbers
  behind the formula — never cached/static.
- **Projection**: next 6 months of scheduled collections from active
  loan schedules, minus the latest finalized payroll total and the
  3-month average of recorded expenses, giving a projected cash figure
  by month end. Labeled an estimate; shown as a table and a chart.
- The Dashboard shows read-only capital summary cards with a link to
  the Capital page — the opening/injection/withdrawal controls live
  only on the Capital page itself.

### 3.7a Assets
- An `asset_types` table is preloaded with: Land, Building, Vehicle,
  Motorcycle, Furniture & Fittings, Computers & Electronics, Office
  Equipment, Machinery, Other. The asset form uses a dropdown against
  this table; CEO/Head Manager can add new types (system configuration,
  not a per-department action). Assets stay tracked separately from
  cash, soft-deletable.

### 3.8 Expenses, Payroll, Leave
- **Expenses**: recorded directly by anyone with `expenses:manage` —
  no approval step, no second Checker.
- **Payroll**: prepare a batch (one line per active employee) →
  preview/edit/remove lines → **finalize** (mark paid) as **one
  action** by whoever holds `payroll:manage` — the same person may
  prepare and finalize; there is no second-person approval. Finalizing
  is blocked (with a clear message) if any line's deductions would
  exceed its gross pay. Payslips are printable/downloadable as PDF per
  employee once a batch is finalized, with a Send option — **every**
  employee's own payslip, not just the first/remaining line.
- **Deductions are itemized, via a configurable Deduction Types
  table** (name, fixed amount / percentage of gross / progressive bands
  such as PAYE, employee-side or employer-side, active flag) — **no
  rate is ever hard-coded**; HR/Head Manager/CEO set every real rate.
  Seeded with placeholders only (PAYE, NSSF, Health Insurance, Loan/
  Advance Repayment), each at a zero rate until configured. Every
  active type's line is shown separately on the payroll preview and the
  payslip: employee-side lines are summed and subtracted to reach net
  pay; employer-side lines (e.g. an employer NSSF match) are shown
  separately as a **cost to the company**, never subtracted from net
  pay. Editing a line's salary recomputes its deduction lines from the
  active types; a direct manual override of the deductions total
  replaces the itemized lines with a single "Manual adjustment" line,
  so the payslip still adds up exactly.
- **Leave requests**: **every tier, with no exception, has a working
  page/action to submit their own leave request** — including a
  Department Manager outside HR (e.g. a Loans Manager), who must never
  be blocked from reaching this page just because their own department
  isn't `hr`. Anyone with `leave:manage` can additionally submit on
  behalf of someone else, and decide any pending request — including one
  they filed themselves. This is a simple request → decide flow, not
  maker-checker. Approval available both inline (on the Leave page) and
  in the central Approvals queue. **A reviewer (Department Manager (HR),
  Head Manager, or CEO) may edit the requested start/end dates before
  approving** — not only a binary approve-as-is/reject — e.g. to resolve
  a calendar or staffing conflict; the originally requested dates are
  preserved (never overwritten) the first time this happens, so what was
  actually asked for is never lost.
- All monetary fields reject negative values at the API level.

### 3.9 Company Settings — removed
There is no Settings page, no `/api/settings/*` route, and no
`company_settings` table. Every former setting (name, address, phone,
email, primary/accent/navy colour, footer text, logo, the default
instalment-rounding step) is now a fixed value in `backend/branding.py`
(frontend mirror: `frontend/src/branding.ts`) — changing any of them
means editing that file and redeploying, never a database write or a UI
action. PDFs, payslips, Excel exports and every email template all read
from there directly (the logo is embedded in emails inline via a CID
attachment, never a blocked external image). A loan's own
`rounding_step` is still copied from the config default at creation and
shown read-only on the loan overview — editing the config never alters
an already-created loan.

### 3.10 Approvals
- Loans and Penalties still show their own pending items with inline
  approve/reject actions on their own page. Leave decisions are
  available both inline (Leave page) and centrally.
- A central Approvals page aggregates loans, penalties and leave
  requests only — expenses, payroll and employees are no longer
  maker-checker gated, so they do not appear there; they are acted on
  directly on their own pages.
- **Every approval-relevant list (pending loans, pending penalties,
  pending leave requests) refreshes itself automatically** when the
  browser tab regains focus, and again on a short interval (~30s) while
  it stays open — a second approver's queue should never go stale just
  because the tab was left open. If an approve/reject action targets a
  record that someone else already decided in the meantime, the response
  names exactly who handled it and when (e.g. "This was already approved
  by Jane Doe at 2026-10-02 14:03") instead of a generic failure.

### 3.11 Reports
- Filterable (date range, product, officer) on-screen reports with KPI
  cards and charts, each exportable as a branded PDF and a styled
  Excel workbook: Portfolio at Risk (with aging buckets and an
  overdue-loan list), Collections (expected vs actual, efficiency %),
  Disbursements, Income Statement (interest + penalties − expenses −
  payroll), Portfolio by Product, Borrower Statement (running
  balance), Cash Flow & Capital, Loan Officer Performance, Expenses by
  Category, plus Payroll and Leave summaries.
- PDF design: header with logo/company name, title, period, generated
  date/user, a KPI summary block, tables with visible borders, header
  shading, zebra rows, right-aligned comma-formatted numbers, a bold
  totals row, a repeated header row per page, "Page X of Y", a
  confidentiality footer, the navy/blue palette, and landscape for wide
  tables.
- Excel design: styled header row, borders, number formats, frozen
  header row, sized columns, a SUM() formula on the totals row, and a
  summary sheet with the report's KPIs.

### 3.12 User Management
- A page reachable by CEO, Head Manager, or a Department Manager (whose
  view is scoped to their own department's staff) to create users
  (choosing a tier limited to what the creating account may hand out,
  and a department for the three scoped tiers), reassign a non-CEO
  account's tier/department within that same hierarchy, see status
  (verified/active), resend a verification link, deactivate (never for
  CEO accounts, never for an account the actor isn't allowed to
  manage), and see days-until-deletion for deactivated accounts
  (auto-deleted after a configurable retention period, with audit
  trail preserved via name/email snapshots).
- **Editing a user is a self-contained modal dialog**, not details that
  load inline below the list — a focused, unambiguous interaction for an
  action that changes someone's access.
- **The users table scrolls horizontally inside its own container** —
  never the whole page sideways — matching the general wide-table rule
  (§4).
- **A pending (unverified) user's row keeps its resend-verification and
  deactivate actions clearly visible and usable.** The deactivate action
  in particular must never be harder to see or reach for a pending user
  than for a verified one.
- **Status and row actions are restrained, not a large coloured pill and
  full buttons** — a small plain-text status label and small text-link
  actions (Edit / Resend link / Deactivate / Reactivate), since this is
  a dense account list, not a one-off confirmation. The same restrained
  pattern is used anywhere this same list-of-accounts shape appears
  (Employees page included).

### 3.12a Employees
- The employee create/edit form's name and phone fields sit correctly
  paired with a sensible tab order between them — not misaligned or
  skipping around.
- **"Create login" for an employee with no login yet** offers tier
  options under the same account-creation hierarchy rules as creating a
  user anywhere else (`assignable_roles_for()`, actor-dependent) — never
  hard-limited to only Maker/Checker, and never restricted to employees
  in the HR department specifically. The action is available (not
  greyed out for an unclear reason) to anyone who could hand out at
  least one tier.
- Status and row actions follow the same restrained pattern as Users
  (§3.12) — a small text status label, text-link actions.

## 4. Non-Functional Requirements

- **Status messages are a floating toast, not a fixed banner.** A
  "saved successfully"/"user created"-style message appears as a toast
  near the bottom of the screen and dismisses itself — it is never
  pinned in the page's layout flow, and no empty reserved space is left
  behind when there is nothing to show.
- **A failed form submission is also a floating toast, AND scrolls to
  and highlights the first invalid field.** No error may appear only
  off-screen above a long form. Applied to the Add Borrower and Create
  Loan forms via a shared `scrollToFirstError()` helper and a `Field`
  `name` prop that any other form can adopt the same way.
- **Every money amount is a WHOLE SHILLING — rounded UP where it's a
  computed figure a client owes, rejected outright (never rounded) where
  it's a direct entry.** The loan schedule's own interest/instalment are
  the one place rounding happens, and it only ever rounds up (never
  down, so the lender is never short) — see §3.3 for the exact rules and
  the instalment-rounding-step setting. Every other money field
  (repayments, penalties, expenses, asset values, capital entries,
  salaries, payroll lines, deductions, settlement, discounts) is
  validated as a whole-shilling INPUT: a fractional amount is rejected
  with "Enter an amount in whole shillings," never silently rounded,
  since these are direct entries, not computed values. Interest RATES
  are the one exception and may keep decimals. Every PDF, the UI, Excel
  exports, and emails display money with commas and NO decimals; Excel
  totals stay formulas. A totals row is always the exact sum of its
  (already whole-shilling) rows — no further rounding decision to make.
  **Loans created before this change may still carry cents in the
  database — left as-is, displayed rounded, never backfilled.**
  **Monetary quantization (generic, non-loan-schedule amounts) is
  Decimal, whole-shilling, consistently.** Every other monetary
  computation — repayments, penalties, expenses, payroll, capital — is
  quantized through the single shared `money()`/`schedule_totals()`
  helpers, never a per-call ad hoc rounding. Any residual left over by
  dividing a total across periods (e.g. an amortization schedule) is
  absorbed entirely in the **final** period, never silently dropped and
  never double-counted across more than one period.
  **Audited, found, and fixed in this pass:** the Portfolio at Risk
  report (`routes/reports.py`) summed outstanding balances with a plain
  `float()` instead of `Decimal`/`money()` — the one place in that file
  that broke from the rest's consistent Decimal quantization; and the
  capital cash-flow projection re-derived its starting cash-on-hand by
  round-tripping an already-serialized float back through `Decimal`
  instead of reusing the Decimal value computed moments earlier — both
  now go through `money()` throughout, with no float sitting in the
  middle of a calculation.
- **Numeric inputs:** thousand-separator formatting while typing
  (e.g. `1,000,000`), reject negative values, reject non-numeric input.
- **Async email:** creating a user or requesting a password reset must
  not block the HTTP response waiting for SMTP — send via a background
  task/queue.
- **Role-based UI:** the frontend must hide or disable actions a
  role cannot perform — never show a button that will always fail with
  "insufficient role" on click.
- **Coherent navigation:** every module accessible from the sidebar
  must be reachable in a way that reflects actual permitted use for the
  logged-in account's permissions — never a link that 403s on click.
- **API base URL:** the browser only ever calls its own origin's
  `/api/*` — never a hardcoded `localhost:5000`, which only resolves on
  the machine actually running the backend. The frontend server
  proxies `/api/*` to the backend container internally (see
  ARCHITECTURE.md §7). This is what fixed the "Unable to connect to
  the API" error on the set-password page in production.
- **Token lifetimes:** verification and password-reset links expire on
  a configurable TTL (`VERIFICATION_TOKEN_TTL_HOURS`,
  `PASSWORD_RESET_TTL_MINUTES`); an expired link shows a clear message
  and a "Send me a new one" option, generic either way (never confirms
  whether an account exists).
- **Layout:** content uses the available width with a sensible
  max-width on very wide screens; a wide table scrolls inside its own
  card, never the whole page; the sidebar collapses on narrow screens.
  On wider screens the sidebar stays genuinely fixed in place — the app
  shell is bounded to exactly the viewport height, and the page content
  area is the one independent scroll region — never the whole document
  scrolling together with (or instead of) the sidebar.
- **Production safety (Phase 2):** the container always starts via
  gunicorn, never the Werkzeug dev server; debug mode and weak/
  placeholder secrets (JWT key, database password, email-service
  secret) are refused outside `ENVIRONMENT=development`; the CEO seed
  script requires `CEO_EMAIL`/`CEO_PASSWORD` with no fallback, refuses
  an obvious or under-12-character password, and forces a password
  change on the CEO's first login.
- **Concurrency safety (Phase 2):** loan/penalty approval or rejection,
  leave decisions, penalty reversal, payroll finalizing, and repayment/
  settlement recording all lock their row before deciding, so two
  concurrent requests for the same record can never both apply — the
  second always gets a clear "already handled by"/"try again" response,
  never a silent double-application.
- **Repayment idempotency (Phase 2):** the repayment and settle forms
  send a one-time key per submission; resending the same key (a
  double-click or a retried request) returns the original result
  instead of recording the payment twice. The Record/Settle button is
  also disabled for the duration of the request.
- **Settlement figure (Phase 2):** the settle panel displays exactly
  the backend's own `settlement_amount` — it never re-derives
  principal + interest itself; only a pending discount (not yet
  submitted) is subtracted client-side as a live preview, never the
  base figure.
- **Rate limiting (Phase 2):** login, forgot-password, resend-
  verification, verify, and set-password are rate-limited per-account
  AND per-IP, counters stored in the database (so the limit holds
  across every gunicorn worker process). Responses stay generic either
  way — a lockout never reveals whether the submitted email exists.
- **Security headers (Phase 2):** both the frontend (Nitro route
  rules) and the backend API set CSP, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy`,
  `Permissions-Policy`, and HSTS when served over HTTPS.
- **Borrower file access (Phase 2):** downloading a borrower's photo
  or ID document requires the same `borrowers:view`/`borrowers:manage`
  permission as the rest of the borrowers module (previously any
  logged-in account could download any borrower's file) and is written
  to the audit log.
- **Test environment mode (Phase 7):** `ENVIRONMENT_LABEL` (unset by
  default — a real production deployment shows nothing) puts a visible
  banner on every page, including the login page, with exactly that
  text. `scripts/reset_dev_data.py` (wipes all users and business data,
  then reseeds a fresh CEO) refuses unless it's run with `--yes`,
  `ENVIRONMENT_LABEL` is set, and `ENVIRONMENT` is not `production`.
  `scripts/seed_demo_users.py` refuses unless `ENVIRONMENT=development`
  exactly — no fake data or demo accounts are ever created in staging
  or production.

## 5. Explicit Out of Scope (For Now)

- Multi-branch support
- SMS-based (non-email/WhatsApp) two-way borrower communication beyond
  reminders
- Anything not listed above — new requests are scoped and agreed
  separately, not silently absorbed into this build.
