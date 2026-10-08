# Loan Management System — Design Document (UX & Interaction Rules)

This document exists because the first build shipped modules that
technically worked but didn't feel like one connected system. These
rules are the fix for that — every screen must follow them, not just
some.

## 1. Core Principle: Nothing Orphaned

Every action must be reachable from the context it naturally belongs
to. A repayment is never entered from a disconnected generic form — it
is entered from that specific loan's own page. A leave approval is
never *only* possible from one giant queue — it's also available right
on the Leave page. If a user has to think "wait, where do I even do
this," that's a design failure, not a missing feature.

## 1a. A Borrower Is Never "Pending"

A borrower record has no approval step of any kind, ever. This has
regressed twice as a purely cosmetic bug — a status badge that implied a
pending/approved state the backend never actually had — so the rule is
stated here explicitly: whatever a borrower's upload/verification state
is, it is never displayed using the same visual language ("pending" /
"approved") as a loan, penalty, or leave request's real approval
workflow. A borrower is simply usable, immediately, from the moment it's
created.

## 1b. A Feature That Isn't Configured Doesn't Show Up

ID verification has no real provider wired in today — `verify_nin()`
always reports `not_configured`. The fix for this is not a nicer "not
configured" message: it's that the whole feature (the status row, the
"Verify ID" button) simply doesn't render at all while nothing is
configured. A permanent placeholder message sitting on every borrower's
page is clutter, not information — once a real provider is wired in, the
same UI reappears automatically, driven by a single `is_configured()`
flag, not a separate code path to remember to re-enable.

## 2. Permission-Aware Everything

- If an account lacks a permission, **the button does not exist for
  them** — not disabled-and-greyed-out, not present-but-throws-an-error
  on click. Gone from the DOM.
- **One narrow, deliberate exception:** the department selector on a
  Checker/Maker's own create/edit form. Department no longer affects
  anything either tier can do, but it's still a real, saved field (useful
  for staff listings/reporting) — so it stays visible and is submitted,
  just **disabled**, not hidden. A Department Manager's own form keeps it
  fully active and required, since their department is what scopes their
  access. This is the one place "show it disabled" beats "remove it
  entirely," because removing it would silently drop a value the record
  still needs.
- Sidebar navigation reflects only what the account's tier + department
  actually allows (`services/permissions.py` on the backend, `lib/api.js`'s
  `hasPermission()`/`hasModuleAccess()` on the frontend — the same logic by
  name on both sides). A Maker never sees "Payroll" — no tier below
  Department Manager ever reaches it, in any department.
- This is a UX rule, not a security rule — the backend is the real
  gate (see Architecture doc §6). The frontend simply should never lie
  about what's possible.
- There is nothing to configure per user beyond tier and department —
  the earlier per-account permission checkboxes are retired entirely.
  Creating or editing a staff account is choosing a tier (limited to
  what the creating account may hand out) and, for the three scoped
  tiers, a department — nothing more.

## 3. Error Messages Say What Actually Happened

| Situation | Message Shown |
|---|---|
| Wrong password | "Incorrect email or password." |
| Unverified account | "Please verify your email before logging in. Check your inbox for the verification link." |
| Session actually expired | "Your session expired. Please sign in again." |
| Wrong role attempting an action | "You don't have permission to do this." (stays on page, no logout) |
| Verification/reset link missing, malformed, expired, or already used | "This link isn't valid" + a "send me a new one" option — checked with the server BEFORE the set-password form ever renders, never after |
| Server error | A plain, non-technical message — never a raw stack trace or generic "error occurred." |

Never reuse one message for a situation it doesn't describe. This was
the single most confusing part of the first-round testing — nearly
every distinct failure said "session expired."

## 4. Numeric Input Standards

- Every money field: comma-formatted thousands separator as the user
  types (`1,000,000`), value stored/sent as a plain number underneath.
- Every money field: negative values physically cannot be entered — not
  just rejected on submit, blocked at the input level (`min="0"` plus
  a keydown guard against the minus key).
- Term-length fields explicitly labeled with their unit (`months`),
  never a bare number with an ambiguous label.

## 5. Loan Creation Is One Flow, Not Two

The calculator preview lives **inside** the loan creation form, updating
live as principal/rate/term are entered. A Maker should never need to
open a separate "Calculator" page, write numbers down, then re-type
them into a "Create Loan" page. One form, one flow, live feedback.

## 5a. A Loan Product Is Optional, and Locks ONLY the Rate

Picking a loan product on the creation form is optional — leaving it on
**"Negotiated rate"** (never "No product") means the Maker enters their
own rate and term directly, through the exact same calculator preview
and amortization function as a product-backed loan. The moment a
product IS picked, only its **rate** field switches to a locked, read-
only display of the product's own value — the **term field stays
exactly as editable as it always is**, bounded only by the product's own
optional min/max term as validation, never forced to the product's
default. (This was a real bug, now fixed: the term used to lock too,
with no way to pick anything else.) The backend enforces the rate lock
the same way regardless of what the form displays.

## 5b. A Paid Schedule Row Shows What Was Actually Paid

Once a schedule row's status becomes "paid," its principal/interest/
payment figures reflect the real repayment that settled it — not the
original scheduled amounts. This only visibly differs from the original
plan when the payment was larger (or, before the loan closes, smaller)
than what was scheduled, so it is easy to miss in casual testing: always
check a paid row after an off-schedule payment, not just an exact-amount
one. **This includes a row settled across more than one partial
payment** — the displayed figures are the CUMULATIVE total across every
repayment ever applied to that row, not just the one that finally closed
it out. A baseline-vs-after simulation of five partial/late-payment
scenarios (run once before any change, once after) is what caught this
exact gap: a row paid off by two partial payments was
only showing the second payment's interest, silently dropping the
first's contribution.

## 5c. Every Money Amount Is a Whole Shilling

There are no cents anywhere in this system any more. A loan schedule's
own interest and instalment are *computed* figures, so they round —
always **UP**, never down, so the lender is never short — the instalment
additionally rounding up to the loan's own stored step (shown on the
loan's own detail page). Every OTHER money field — a repayment, a
penalty, an expense, an asset value, a capital entry, a salary, a
payroll line, a settlement discount — is a *direct entry*, so it is
never rounded: a fractional amount is flatly rejected with "Enter an
amount in whole shillings." Interest rates are the one field that keeps
decimals (10.5% is a real rate, not a shilling amount). Every PDF, every
screen, every Excel export, every email shows money with commas and NO
decimals — a loan created before this change may still carry cents in
the database; it is simply displayed rounded, never backfilled.

## 5d. Early Settlement Shows Its Breakdown Before It Commits

Settling a loan early shows principal, this period's interest, any
discount, and the total to settle — never just a single number to
accept blind (the same philosophy as §8's confirmation pattern, applied
here specifically). Only a Loans Manager, Head Manager, or CEO ever sees
the discount field at all; a Maker or Checker sees the same breakdown
with no discount option, and can still settle plainly. Typing more than
the settlement amount into a plain repayment says exactly what the most
payable today is, never a generic "amount too large."

## 6. Approval Pattern — Loans and Penalties Only

Maker-checker now applies to exactly two modules: Loans and Penalties.
Both follow the identical pattern:

```
[ Module List Page ]
  ├── "Pending Approval" section at the top — inline Approve/Reject
  │   buttons right there, visible only to someone who holds the
  │   matching *:approve reach for that record's department and did
  │   NOT create it (CEO/Head Manager/Department Manager are the one
  │   exception — see §6a)
  └── Regular list below

[ Approvals Page ]
  └── Same pending loans/penalties, aggregated, for a user who wants
      one place to review everything at once — plus pending leave
      requests, decided directly (see §6b)
```

Both views read from the same data — never a separate "approval copy"
of a record that can drift out of sync with the real one.

**Every one of these lists keeps itself fresh.** A pending-approval list
reloads on window focus/visibility regaining and again every ~30s while
it's open (`useAutoRefresh`) — a second approver should never act on a
queue that quietly went stale while their tab sat in the background. If
they try to decide a record someone else already handled in the
meantime, the response is never a generic failure: it names exactly who
handled it and when ("This was already approved by Jane Doe at 2026-10-02
14:03").

A real change from the previous design: **penalty approval is no
longer a Checker action at all**, in any department — only Department
Manager and above hold it now. A Checker still approves loans, and
(simplified further since) with **no department restriction at all**
any more — any Checker can approve any loan.

Expenses, Payroll and Employees are **not** on this pattern: they are
recorded or finalized directly by whoever holds the matching module
access, in one action, on their own page — never a second-approver
step, and never listed on the Approvals page.

### 6a. Self-Approval — Exempt Tiers, No Tracking

A Checker or Maker can never approve their own loan or penalty — no
exception. A CEO, Head Manager, or Department Manager *may* approve
their own — and, under the current design, **this is never marked in
any way**: no badge, no flag, no separate audit action. The approval
is recorded exactly like any other. (An earlier revision of this
system showed a "Self-approved" badge and filter here; that has been
deliberately removed.)

### 6b. Leave — A Decision, Not an Approval Queue Item in the Same Sense

Leave requests are a simple request → decide flow. Anyone whose
department reaches the leave module (Department Manager (HR), Head
Manager, or CEO) can decide any pending request, including one they
filed themselves or on someone else's behalf — there is no
creator-must-differ rule here, unlike loans and penalties. A Checker or
Maker is never among them, in any department, no exception — they can
only ever request leave for themselves, and critically, **every tier
without exception has a working page/action to do so** — including a
Department Manager outside HR, who must reach this page for their own
request the same as anyone else.

Deciding a leave request is never *only* a binary approve-as-is/reject:
the reviewer opens the same `LeaveDecisionModal` from either the Leave
page or the Approvals queue, which lets them edit the requested start/end
dates before approving (e.g. to resolve a staffing conflict) without
forcing a reject-and-resubmit round trip. The originally requested dates
are preserved the first time this happens — an editing reviewer should
never be able to make what was actually asked for disappear.

## 6c. Editing Is a Self-Contained Modal, Never Inline-Below-The-List

Editing a record (a user's tier/department, a pending leave request's
dates before approving) opens a focused modal dialog — Escape or a
backdrop click closes it, the page behind it never scrolls while it's
open. The previous pattern of loading details inline below the list on
click is retired: it's ambiguous about what's being edited and easy to
lose track of when the list itself re-renders underneath it.

## 6d. A Reference To Another Record Is Always a Full Link

Wherever a loan (or any other record) is referenced by its number — "Loan
#5", "#12" in a table cell — the **entire identifier** is the clickable
link, not just the "#" character with the number sitting next to it as
plain text. A user should be able to click anywhere on "Loan #5" and
land on that loan.

## 6e. A Dense Account List Is Restrained, Not Decorated

Users and Employees are long, row-dense lists people scan quickly, not a
one-off confirmation. A large coloured status pill and a row of full
buttons per account is too heavy for that density — it reads as several
separate decisions per row instead of one glance. A small plain-text
status label and small text-link actions (Edit · Resend link ·
Deactivate · Reactivate) carry the same information and the same
affordance to click, at the right visual weight for a list this dense.
This is deliberately NOT the rule for a loan/penalty/leave's own status
badge (§7/§10) — those stay pills; this restrained treatment is specific
to an account-style list, and applies the same way everywhere that same
shape of list appears.

## 6f. A Failed Form Submission Is Findable, Not Just Present

A validation error that only renders as a small red line above a field
far down a long form is easy to miss entirely — the page doesn't visibly
react, so the person re-clicks "Save" wondering why nothing happened.
Every failed submission therefore does two things together: shows the
error as a floating toast (so it's visible regardless of scroll
position) AND scrolls to and briefly highlights the first invalid field,
so the person lands exactly where the fix is needed. Neither alone is
enough — the toast says something is wrong, the scroll-and-highlight
says exactly where.

## 7. Status Language — Plain, Not Technical

Show borrowers and staff human language, not database enum values:

| Internal Status | Displayed As |
|---|---|
| `pending_approval` | "Waiting for approval" |
| `active` | "Active" |
| `closed` | "Fully paid" |
| `rejected` | "Rejected — [reason]" |
| `partial` (repayment) | "Partially paid" |
| `missed` | "Payment missed" |
| `draft` (payroll batch) | "Draft" |
| `paid` (payroll batch) | "Paid" |
| `cancelled` (payroll batch) | "Cancelled" |
| `recorded` (expense) | "Recorded" |

## 8. Every Money-Moving Confirmation Shows the "Why"

When a Checker approves a penalty, the confirmation shows *what will
happen* before they confirm: "This will add TZS 5,000 to Loan #TZ-0004's
outstanding balance." Don't make an approver click blind — show the
consequence before the action commits.

## 8a. Status Messages Are a Floating Toast, Not a Fixed Banner

"Saved successfully," "User created," and the like appear as a toast
near the bottom of the screen that dismisses itself — never a banner
pinned in the page's normal layout flow. A banner reserves space for
itself even when there's nothing to show, which is its own small bug;
a toast reserves nothing when idle.

## 9. Print/Export Everywhere Money Is Summarized

Payslips, loan schedules, borrower statements, and all five reports
must have a visible, working "Download PDF" / "Print" action on the
page itself — not buried, not missing, not requiring a separate export
tool.

## 10a. Layout Never Breaks the Viewport

- Page content is capped at a sensible max-width on very wide screens
  (ultra-wide monitors) rather than stretching tables and forms edge to
  edge.
- A wide table scrolls **inside its own card** — never the whole page.
  The page itself must never gain a horizontal scrollbar. This applies
  to every wide table, the Users table included — it was the one
  concrete regression this rule caught: a table wide enough to push the
  whole page sideways instead of scrolling within its own card.
- A row's available actions are never harder to see for one status of
  that record than another. A pending (unverified) user's row keeps its
  resend-verification and deactivate actions exactly as visible and
  reachable as an active user's row — status is never an excuse for an
  action to quietly become harder to find.
- The sidebar collapses behind a menu toggle on narrow screens; on wider
  screens it stays genuinely **fixed in place** — page content is the one
  scrolling region, never the sidebar moving with it, and never the whole
  document scrolling together.

## 10. Visual Consistency

- The primary/accent colours and footer text come from Company Settings
  (Phase 4), not a hardcoded hex — navy is only the *default* a new
  installation starts with. Frontend UI, email templates, and generated
  PDFs/Excel all read the same settings row, so a colour change in one
  place changes every surface.
- Status badges use consistent colors system-wide: green = good/active,
  amber = pending, red = rejected/overdue, grey = closed/inactive. This
  is a **closed set of four** — nothing gets a fifth hue. (Phase 5 found
  and fixed one drift from this: "approved" was rendering in blue; it is
  green now, same as "active", since approval is a positive outcome.)
- The full token layer (type scale, spacing scale, radius, shadow,
  button/table/badge sizing, the shared list/search/pagination
  components) is specified in [docs/design-system.md](docs/design-system.md) —
  Phase 5's consolidation of what had drifted into inconsistent spacing,
  a card shadow, pill-shaped badges, and an unloaded font declaration
  across `styles.css`. That document is the one to update when a new
  page is built or an existing one is revisited; this section stays the
  short summary.
