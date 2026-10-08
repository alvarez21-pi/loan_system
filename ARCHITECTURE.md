# Loan Management System — Architecture Document

## 1. System Overview

```
[ React frontend ]  <-- REST/JSON -->  [ Flask backend API ]  <---> [ PostgreSQL ]
                                                |
                                                v
                                     [ PHP Email Microservice ]
                                                |
                                                v
                                          [ SMTP Provider ]
```

Four containers, orchestrated by `docker-compose.yml`, deployed via
Coolify on a VPS. Each container has exactly one responsibility.

## 2. Containers

| Container | Responsibility | Talks To |
|---|---|---|
| `frontend` | TanStack Start (React) app, server-rendered by its own Node/Nitro server | `backend` (proxies `/api/*` — see §7) |
| `backend` | Flask REST API — all business logic, validation, auth | `db`, `email-service` |
| `db` | PostgreSQL — single source of truth for all data | `backend` only |
| `email-service` | PHP/PHPMailer — sends transactional email | SMTP provider, called by `backend` |

No container talks directly to a container it isn't listed as talking
to above. The frontend never calls the email service directly, and
never talks to the database directly — everything goes through the
backend API, and the browser never talks to the backend directly
either (see §7).

## 3. Backend Structure

```
backend/
  app.py                  — app factory, extension init, blueprint registration
  extensions.py            — SQLAlchemy, JWT, Migrate instances
  seed_ceo.py               — idempotent: CEO user + linked Employee + asset
                              types + a default company-settings row
  scripts/
    reset_dev_data.py         — wipes all users/business data, reseeds the CEO.
                                Refuses unless ALLOW_DEV_RESET=true, and always
                                refuses when FLASK_ENV=production. Dev only.
  models/
    user.py                — User (role: ceo/head_manager/department_manager/
                             checker/maker, department: hr/finance/loans_credit/
                             general — required for the three scoped tiers, null
                             for the two unscoped ones; purely descriptive for
                             checker/maker now — see services/permissions.py).
                             No per-user permission table any more —
                             display_role derives the UI title ("HR Manager"
                             etc. for a department_manager). credentials_version
                             bumps every time a setup/reset token is consumed,
                             so any other outstanding token for that user
                             stops validating immediately (single-use links).
    borrower.py             — Borrower: id_type (nida/driving_licence/voter_id/
                             passport/other) + id_number (unique together),
                             id_verified/id_verified_at/id_verification_source
    loan.py                 — LoanProduct (default_term_months is now
                             vestigial — kept for backward compatibility only;
                             a selected product locks ONLY its rate, never its
                             term, since 16-part-v2 Part 2 — min/max_term_months
                             are the real, validation-only term bounds now),
                             Loan (loan_product_id nullable — a negotiated-
                             rate loan has none; rounding_step — copied from
                             the company default AT CREATION, never changes
                             later even if the setting does; decided_at —
                             when an approve/reject decision was made, so a
                             stale second approver can be told who beat them
                             to it and when), PaymentSchedule, Repayment,
                             Penalty (decided_at too). No self_approved
                             column on either — the tier model tracks/badges
                             no self-approval at all.
    accounting.py            — Asset (+ asset_type_id), AssetType, Expense
                             (recorded directly, no approval columns), CapitalEntry
                             (entry_type: opening/injection/withdrawal),
                             CompanySettings (name/address/phone/email/logo,
                             instalment_rounding_step — default 1,000, CEO/
                             Head Manager editable, only affects NEW loans)
    employee.py               — Employee, LeaveRequest (approval_permission =
                             "leave:manage", simple decide flow, not maker-checker;
                             decided_at; original_start_date/original_end_date —
                             set the first time an approver edits the requested
                             dates before approving, preserving what was actually
                             asked for), PayrollBatch (draft -> paid -> cancelled,
                             single-action finalize) + PayrollRun (per-employee
                             lines — deductions is now the sum of EMPLOYEE-side
                             PayrollDeductionLine rows only; employer_cost is
                             the sum of EMPLOYER-side ones, shown separately,
                             never subtracted from net_pay), DeductionType
                             (name, calculation: fixed/percentage/bands, side:
                             employee/employer, is_active — no rate ever
                             hard-coded, every real rate set here) +
                             PayrollDeductionLine (one per deduction per run,
                             snapshotted name/side so a later rename/
                             deactivation never changes a historical payslip)
    audit.py                   — AuditLog (with actor name/email snapshot columns)
  routes/
    auth.py                     — login, register (role + department +
                                  employee_option: create/link/none, gated by
                                  services/permissions.can_create_tier — never
                                  touches or invalidates the CREATING user's
                                  own token/session), password-reset/validate
                                  (public, token-only pre-check the set-
                                  password page calls BEFORE ever rendering
                                  the form — checks signature, per-purpose
                                  TTL, and single-use via
                                  User.credentials_version, without consuming
                                  anything), password reset/setup confirm
                                  (same checks, then consumes the token and
                                  bumps credentials_version), resend-
                                  verification (generic response)
    resources.py                  — borrowers, loan-products, loans, repayments,
                                  expenses, penalties lists (read-only; names
                                  resolved, can_decide/can_reverse computed
                                  server-side — no self_approved anywhere);
                                  audit-logs (audit:view — CEO/head_manager only)
    operations.py                  — loans (loan_product_id optional —
                                  "Negotiated rate"; a selected product locks
                                  ONLY its rate server-side, client rate value
                                  ignored outright; the TERM is always the
                                  client's own value, checked only against the
                                  product's optional min/max as bounds — never
                                  locked, a real bug fix), repayments
                                  (apply_repayment(): schedule = plan,
                                  repayments = reality; a row that becomes
                                  "paid" has its principal/interest/payment
                                  overwritten with the CUMULATIVE real
                                  repayment split across every repayment ever
                                  applied to it — not just the last one, a
                                  second bug the Part 0 baseline simulation
                                  caught — never left at stale scheduled
                                  figures; every amortization call passes the
                                  loan's own rounding_step), settle_loan()
                                  (/loans/<id>/settle — early settlement with
                                  an optional, reason-required interest
                                  discount gated on settlement:discount,
                                  capped at the open row's own interest, logged
                                  via a SETTLEMENT_DISCOUNT audit entry; the
                                  discount is applied to the schedule BEFORE
                                  the one shared apply_repayment() path runs),
                                  penalties (money-critical + maker-checker),
                                  expenses (direct, no approval), capital
                                  (opening/injections/withdrawals/summary/
                                  projection), assets + asset-types, leave
                                  (decide_leave() accepts an optional start_date/
                                  end_date override on approval). parse_money()
                                  now REJECTS a fractional amount ("Enter an
                                  amount in whole shillings.") instead of
                                  rounding it — every money INPUT field is a
                                  whole shilling. validated_upload()
                                  (renamed from validated_image) accepts a PDF
                                  (pypdf) alongside an image (Pillow) for borrower
                                  photo/ID uploads, both now optional at creation.
                                  already_handled_response() builds the "already
                                  approved/rejected by X at Y" 409 body shared by
                                  loan/penalty/leave decide endpoints.
                                  company_rounding_step() reads the current
                                  CompanySettings.instalment_rounding_step for a
                                  NEW loan only.
    reports.py                      — the report endpoints: portfolio-at-risk,
                                      collections, disbursements, income-statement,
                                      portfolio-by-product, borrower-statement,
                                      cash-flow, loan-officer-performance,
                                      expenses-by-category, payroll-summary,
                                      leave-summary. Each supports
                                      ?format=pdf|excel via services/pdf.py and
                                      services/excel.py; gated by reports:view or
                                      reports:financial (services/permissions.py)
    users.py                         — user management (CEO, Head Manager, or a
                                      Department Manager scoped to their own
                                      department's staff): create/reassign a
                                      non-CEO account's tier + department within
                                      can_create_tier()'s hierarchy, resend-
                                      verification, link-employee
    employees.py                      — employee CRUD, soft deactivate, link-user,
                                      create-login (for an employee with no login
                                      yet, prefilled with their email), duplicate
                                      (same name+phone) warning. link-user and
                                      create-login are gated by the new
                                      account_creator_required decorator (the
                                      general account-creation hierarchy,
                                      assignable_roles_for() — actor-dependent tier
                                      options), not the HR-specific
                                      employees:manage permission — so any manager
                                      who could hand out a tier can use either
                                      action, not only HR
    payroll.py                         — batch create/preview/edit-line/remove-line
                                      (build_deduction_lines() computes every
                                      active DeductionType's line for the
                                      employee's gross; editing a line's salary
                                      recomputes them; a manual `deductions`
                                      override instead replaces them with one
                                      "Manual adjustment" line), finalize
                                      (single action, marks paid, blocked with
                                      a clear message if any line's deductions
                                      exceed its gross) / cancel, payslip PDF +
                                      send, deduction-types CRUD
                                      (payroll:manage; compute_deduction_amount()
                                      handles fixed/percentage/progressive-bands
                                      calculation, each a whole-shilling amount)
    settings.py                         — company settings (name/address/phone/
                                      email/logo, instalment_rounding_step),
                                      settings:manage only
  services/
    loan_calculator.py                — SINGLE shared amortization function, now
                                         whole shillings rounded UP only (never
                                         down - the lender is never short).
                                         money() is the generic whole-shilling
                                         quantizer (HALF_UP, clamped >=0, never
                                         "-0"); whole_up() rounds a row's own
                                         interest UP to the next shilling;
                                         round_up_to_step() rounds the (once-
                                         computed, unrounded) EMI UP to the next
                                         multiple of the loan's own rounding
                                         step (default 1,000). A row's payment
                                         can never exceed that row's own
                                         remaining balance + interest - whichever
                                         row that happens on (the natural last
                                         period, or an earlier one for a small
                                         loan/chunky step) closes the loan out
                                         exactly there and the schedule ends,
                                         never padded with trailing zero rows.
                                         Standard EMI (equal monthly
                                         installment) amortization otherwise
                                         unchanged: monthly payment = P * r *
                                         (1+r)^n / ((1+r)^n - 1), where r = the
                                         MONTHLY rate as entered (10% -> 0.10),
                                         used directly, NO division by 12. Used by
                                         both the calculator preview endpoint
                                         AND loan creation, and re-run on
                                         remaining balance/remaining term
                                         whenever the flexible scheduler
                                         reconciles a real repayment. Never
                                         duplicated.
    permissions.py                      — THE tier + department model. Retires
                                         the per-user permission-matrix table
                                         entirely (Part 0). `loan_products:manage`
                                         maps to the `loans` module, so a Loans
                                         Manager (department_manager, loans_credit)
                                         reaches it the same way they reach
                                         loans/borrowers/repayments/penalties —
                                         previously CEO/head_manager only.
                                         DEPARTMENT_MODULES maps each of hr/finance/
                                         loans_credit/general to the modules it
                                         reaches —
                                         the source of truth for department_
                                         manager/head_manager/ceo ONLY.
                                         CHECKER_PERMISSIONS/MAKER_PERMISSIONS
                                         are each tier's fixed, small action
                                         set, department-INDEPENDENT: a
                                         checker approves any loan and creates
                                         borrowers/repayments/expenses/
                                         penalties/own-leave in every
                                         department alike; a maker does the
                                         same list plus loans:create, never
                                         approves anything. Neither ever
                                         approves a penalty or a leave request
                                         — department_manager and above only.
                                         has_permission(user, permission) is
                                         the ONE function every endpoint calls.
                                         can_create_tier()/can_manage_user()/
                                         assignable_roles_for() are the
                                         separate account-creation hierarchy
                                         (CEO -> Head Manager -> Department
                                         Manager -> Checker/Maker), unchanged
                                         by the checker/maker simplification.
    approval.py                         — maker-checker, narrowed to loans and
                                         penalties only. approval_denial(user,
                                         record) returns None (allowed),
                                         SELF_APPROVAL, NOT_AN_APPROVER or
                                         OUT_OF_SCOPE. CEO/head_manager/
                                         department_manager are exempt from the
                                         self-approval block — with NO
                                         self-approved flag, badge or audit
                                         distinction of any kind. A checker
                                         approves loans only (never leave,
                                         never a penalty, in any department);
                                         a maker never approves anything;
                                         department_manager and above hold
                                         penalty and leave approval. This is
                                         the only place these rules live.
    identity_verification.py             — verify_nin(id_number, id_type): a
                                         seam, not an integration. Always
                                         returns {"status": "not_configured"}
                                         today — no unofficial NIDA scraper is
                                         used. is_configured() (backed by the
                                         PROVIDER_CONFIGURED constant, False
                                         today) is exposed on every borrower
                                         as id_verification_configured — the
                                         frontend hides the entire verification
                                         UI while it's False, never showing a
                                         permanent "not configured" message.
                                         normalize_nida() strips dashes/spaces
                                         for storage.
    accounts.py                          — shared login creation (Users page,
                                         Employees page, and the retroactive
                                         create-login action) — create_login()
                                         enforces can_create_tier() itself, so
                                         every entry point is held to the same
                                         hierarchy; department parsing,
                                         resend-verification. reset_token()
                                         embeds the target user's current
                                         credentials_version. send_email_async()
                                         now checks send_email()'s result and
                                         logs a clear error on failure — it
                                         used to be silently discarded even on
                                         a hard connection failure, which was
                                         the real cause behind "the first
                                         verification email sometimes needs a
                                         resend."
    pdf.py                                — branded (navy/blue, company logo
                                         from CompanySettings) schedule and
                                         payslip PDFs, plus report_pdf(): the
                                         generic report layout (KPI cards,
                                         bordered zebra table, right-aligned
                                         money, bold totals row, repeated
                                         header row, "Page X of Y", a
                                         confidentiality footer, landscape
                                         option for wide tables)
    excel.py                              — styled Excel export: header
                                         fill/border, money number format,
                                         frozen header row, sized columns, a
                                         SUM() formula on the totals row, and
                                         a Summary sheet carrying the KPIs
    email_client.py                       — HTTP client calling email-service;
                                         retries a bounded couple of times on
                                         a connection-level failure only
                                         (e.g. email-service not accepting
                                         connections yet right after
                                         `docker compose up`), never on a
                                         real application-level failure
    scheduler.py                           — APScheduler jobs: payment
                                          reminders, deactivated-user deletion
                                          sweep
  migrations/                              — Alembic. Latest two: loans.
                                            rounding_step + company_settings.
                                            instalment_rounding_step (both
                                            default 1,000); deduction_types +
                                            payroll_deduction_lines tables +
                                            payroll_runs.employer_cost, seeded
                                            with 4 zero-rate placeholder types
                                            (PAYE/NSSF/Health Insurance/Loan
                                            Advance Repayment). Earlier:
                                            nullable loan_product_id +
                                            LoanProduct.default_term_months;
                                            decided_at on loans/penalties/
                                            leave_requests + original_start_date/
                                            original_end_date on leave_requests
  tests/                                    — pytest: calculator math, the
                                            tier + department model's unit
                                            tests, self-approval (allowed, with
                                            no tracking, for ceo/head_manager/
                                            department_manager, still blocked
                                            for maker/checker), the account-
                                            creation hierarchy, opening-
                                            capital-once, borrower duplicate-ID
                                            blocking, token expiry with a tiny
                                            TTL, the full set-password flow,
                                            negative-value rejection, workflow
                                            end-to-end, a paid schedule row
                                            matching the real repayment split
                                            exactly on an overpayment with the
                                            totals row reconciling to original
                                            principal, a new borrower having no
                                            pending state, a Loans Manager
                                            managing loan products, a
                                            negotiated (no-product) loan, and a
                                            product's rate being locked
                                            server-side (never its term) even
                                            when the request tries to
                                            override it.
                                            test_partial_payment_baseline.py —
                                            NOT a correctness test: five
                                            partial/late-payment scenarios run
                                            once against the UNMODIFIED
                                            repayment logic and again
                                            against the final code,
                                            specifically to separate rounding-
                                            driven differences from anything
                                            else. Also: whole-shilling rounding
                                            (instalment/interest rounded up,
                                            the stored rounding step surviving
                                            a later company-setting change,
                                            every money field rejecting a
                                            fractional amount), early
                                            settlement with a capped, reason-
                                            required discount restricted to
                                            Loans Manager/Head Manager/CEO,
                                            itemized payroll deductions
                                            (percentage/fixed/progressive
                                            bands, employer-side shown
                                            separately), and a finalize blocked
                                            when deductions exceed gross pay.
```

**Key rule:** `loan_calculator.py` is called from exactly two places —
the standalone preview endpoint and the loan-creation endpoint (plus the
repayment reconciler, which re-runs the SAME function). If a third
calculation path is ever added, that's a bug, not a feature.

**Key rule:** `services/permissions.py`'s `has_permission()` is the only
place a permission check is decided. Every write endpoint (and every
read endpoint that needs gating) calls it, directly or through
`routes/operations.py`'s `permission_required(*permissions)` decorator.
Do not reimplement a role check per-module.

**Key rule:** `services/approval.py`'s `approval_denial()` is the only
place maker-checker (loans/penalties only) is decided, including the
CEO/head_manager/department_manager self-approval exemption (with no
self-approved tracking of any kind). Do not reimplement it per-module.

**Known simplification:** list/detail (read) endpoints for loans,
penalties, borrowers, etc. remain open to any authenticated user
(`@auth_required` only), matching the original app's behavior — the
permission matrix gates *write* actions (create/approve/manage)
precisely, not every read. If per-field/per-list read gating is wanted
later, that's a deliberate follow-up, not an oversight.

## 4. Frontend Structure

```
frontend/src/
  routes/
    index.tsx                — login, password reset request/confirm, and an
                              expired-link "send me a new one" flow
    dashboard.tsx              — portfolio summary + read-only capital cards
                                (link to /capital — no capital controls here)
    borrowers.index.tsx         — list + create (id_type dropdown, duplicate-ID
                                block with a link to the existing borrower)
    borrowers.$id.tsx            — detail, ID verification action
    loan-products.tsx               — gated on loan_products:manage, not
                                    admin-only — reachable by a Loans Manager
    loans.index.tsx                — list, create WITH embedded calculator
                                    preview (loan_product_id optional — a
                                    negotiated loan when left blank; rate/term
                                    inputs disable and show the product's own
                                    values once one is selected), inline
                                    pending-approval section, auto-refreshing
                                    (useAutoRefresh)
    loans.$id.tsx                  — detail, schedule, repayments entered here
                                    via the shared <RepaymentForm>
    penalties.tsx                    — list, create, inline approve/reject,
                                        reverse action, auto-refreshing
    capital.tsx                        — NEW: opening capital setup/correction,
                                        injections/withdrawals, cash-on-hand
                                        breakdown, 6-month projection + chart
    assets.tsx                           — asset list/create with an asset-type
                                        dropdown (+ add new type)
    repayments.tsx                        — pick a loan first, then the SAME
                                        shared <RepaymentForm> used on the
                                        loan's own page — one entry point's
                                        logic, not a duplicate of the other's
    expenses.tsx                          — record directly, no approval UI
    employees.tsx                          — create-login action (tier options
                                        via assignable_roles_for(), actor-
                                        dependent — not maker/checker-only,
                                        not HR-only), link-to-user, edit (name/
                                        phone paired with a sensible tab
                                        order), soft deactivate
    payroll.tsx                             — prepare, preview/edit/remove lines
                                        (itemized deduction lines shown per
                                        employee-side/employer-side), finalize
                                        (single action) / cancel, payslip PDF +
                                        send (every employee's own line)
    deduction-types.tsx                       — NEW: configurable deduction/
                                        contribution types (fixed/percentage/
                                        progressive bands, employee/employer
                                        side) — payroll:manage only
    leave-requests.tsx                       — create (self — every tier,
                                        unconditionally — or for anyone with
                                        leave:manage), review via the shared
                                        <LeaveDecisionModal> (editable start/
                                        end dates before approving), auto-
                                        refreshing
    approvals.tsx                             — aggregated queue: loans,
                                        penalties, leave ONLY; auto-refreshing
                                        (useAutoRefresh on focus/interval);
                                        leave rows reviewed via the same
                                        <LeaveDecisionModal> as the Leave page;
                                        a stale decide attempt surfaces the
                                        backend's "already handled by X at Y"
                                        message as-is
    reports.tsx                                — filterable (date range,
                                        product, officer), KPI cards, a
                                        chart where useful, PDF/Excel export
    settings.tsx                                — NEW: company name/address/
                                        phone/email/logo
    audit-logs.tsx                               — audit:view permission
                                        (CEO/head_manager only)
    users.tsx                                   — create users (tier limited to
                                        assignableRolesFor(actor), department
                                        for the three scoped tiers — shown but
                                        disabled on a checker/maker's own
                                        form, since it no longer gates
                                        anything for them), reassign a non-CEO
                                        account's tier/department within that
                                        same hierarchy via a self-contained
                                        edit <Modal> (not inline details),
                                        resend-verification, deactivate — both
                                        actions stay clearly visible for a
                                        pending (unverified) row too. The
                                        table scrolls horizontally inside its
                                        own card (`min-w-0`), never the page.
                                        No permission checkboxes any more
                                        (Part 0).
  components/
    LeaveDecisionModal.tsx                    — shared leave approve/reject
                                                dialog used identically by
                                                leave-requests.tsx and
                                                approvals.tsx: lets the
                                                reviewer edit the requested
                                                start/end dates before
                                                approving
    RepaymentForm.tsx                           — shared repayment-recording
                                                form used identically by
                                                loans.$id.tsx and
                                                repayments.tsx; also renders
                                                SettleLoanPanel (early
                                                settlement breakdown —
                                                principal/interest/discount/
                                                total; the discount field only
                                                shows for an actor with
                                                settlement:discount)
    AppShell.tsx                              — nav filtered by permission/
                                                module access (services/
                                                permissions.py's logic mirrored
                                                in lib/api.js); a module/
                                                permission a user lacks does
                                                not show its nav item at all;
                                                content capped at a sensible
                                                max-width, tables scroll
                                                inside their own card, the
                                                sidebar collapses on narrow
                                                screens. The shell itself is
                                                bounded to exactly the
                                                viewport height (`h-screen
                                                overflow-hidden`) with a
                                                single independent scroll
                                                region on <main> — the
                                                sidebar (and header) stay
                                                genuinely fixed in place
                                                while page content scrolls;
                                                the earlier `min-h-screen` +
                                                document-level-scroll
                                                approach was unreliable (an
                                                `overflow-x: hidden` on an
                                                unbounded-height ancestor
                                                forces an implicit
                                                `overflow-y: auto` that never
                                                actually gets to scroll,
                                                which is what broke it)
    lms-ui.tsx                                 — shared buttons, tables, badges,
                                                number inputs with formatting
                                                (money() now 0dp - whole
                                                shillings, commas, no
                                                decimals; MoneyInput defaults
                                                to 0 decimals), Modal (self-
                                                contained dialog — Escape/
                                                backdrop close, body-scroll-
                                                locked while open), and
                                                ToastContainer (renders the
                                                lib/toast.js store — a status
                                                message is a floating toast
                                                near the bottom of the screen,
                                                never a fixed banner reserving
                                                layout space). StatusLabel/
                                                TextLink: a restrained, small-
                                                text alternative to
                                                StatusBadge/Button for a dense
                                                account list (Users,
                                                Employees) — same status
                                                vocabulary/colors, just not a
                                                pill or a full button. Field
                                                takes an optional `name`; a
                                                failed submit calls
                                                scrollToFirstError(errors) to
                                                scroll to and briefly
                                                highlight (`.lms-field-
                                                highlight`) the first invalid
                                                one.
  hooks/
    useAutoRefresh.js                            — reloads an approval-
                                                relevant list on window focus/
                                                visibilitychange and every
                                                ~30s while the tab stays
                                                visible; used by approvals.tsx,
                                                loans.index.tsx, penalties.tsx,
                                                leave-requests.tsx
  lib/
    toast.js                                     — module-level toast pub/sub
                                                    store (showToast/
                                                    subscribeToasts/
                                                    dismissToast), mounted
                                                    once via AppShell's
                                                    <ToastContainer />
    api.js                                      — API client; distinguishes
                                                    401 (logout) from 403
                                                    (in-place permission
                                                    message); hasPermission()/
                                                    hasAnyPermission()/
                                                    hasModuleAccess()/
                                                    assignableRolesFor()/
                                                    roleLabel() mirror the
                                                    backend's tier + department
                                                    logic byte-for-byte
                                                    (checker/maker have no
                                                    department gating here
                                                    either); BASE_URL
                                                    defaults to "" (same
                                                    origin) — see §7. The
                                                    session (token + cached
                                                    user) lives in
                                                    sessionStorage, not
                                                    localStorage — see §6.
```

**Key rule:** permission-based visibility is enforced in `AppShell.tsx`'s
nav rendering AND independently re-checked by the backend on every
request. Hiding a nav item is a UX convenience, never the actual
security boundary — the API enforces the real rule regardless of what
the UI shows.

## 5. Data Flow — Loan Creation (unchanged from v2, still current)

```
Maker opens "New Loan" form
        |
        v
Maker enters principal / rate / term
        |
        v
Frontend calls POST /api/loan-calculator/preview on every change
(debounced) --> renders live schedule table on the SAME screen
        |
        v
Maker submits --> POST /api/loans
        |
        v
Backend calls the SAME loan_calculator.py function internally
to persist the PaymentSchedule rows --> guarantees preview
always matches what's actually stored
        |
        v
Loan status = pending_approval, visible immediately with its
schedule on the loan's own detail page
        |
        v
A Checker (department-scoped), Department Manager, Head Manager or CEO
approves — never the creator, unless CEO/head_manager/department_manager
(then allowed, with no self-approved flag or tracking of any kind) —
from either the loan's own page OR the central Approvals queue
        |
        v
On approval: schedule delivered to borrower (email if on file,
PDF export, WhatsApp send)
```

## 6. Security Boundaries

- JWT access token (short-lived; no refresh token and no cookie-based auth
  exist in this app at all — `JWTManager` uses its default header-only
  token location, confirmed by audit, so there is nothing cookie-related
  to worry about tab-isolating).
- The token (and the cached user derived from it) lives in the browser's
  `sessionStorage`, not `localStorage` — deliberately, so each tab is an
  independent session. `localStorage` is shared by every tab of the same
  origin; that sharing was the root cause of three real bugs: logging into
  a different account in one tab silently changing what another tab
  showed, and a token-only page (verification/reset) rendering off
  whichever session happened to be sitting in shared storage instead of
  the token actually in its own URL.
- `401` = invalid/expired token → frontend clears session, redirects to login.
- `403` = valid session, insufficient permission → frontend shows an
  in-place message, session untouched.
- The verification/password-reset page never shows its set-password form
  on the strength of the URL alone: it calls `POST /api/auth/password-
  reset/validate` first (public, token-only, no Authorization header sent)
  and only renders the form once that comes back `{"valid": true}`. A
  missing, malformed, expired, or already-used token shows a "this link
  isn't valid" state with a "send me a new one" option instead. Every
  setup/reset token is single-use: it carries the target user's
  `credentials_version` at issue time, and confirming a token bumps that
  version, which immediately invalidates that token AND any other
  outstanding one for the same user (e.g. from an earlier resend).
- Every write endpoint re-validates the permission server-side via
  `has_permission()` — the frontend hiding a button is never the only
  protection.
- All monetary fields validated server-side as `Decimal`, rejecting
  negative or non-numeric values, independent of frontend validation.
- CEO accounts are protected by an explicit guard in every
  user-modifying endpoint (`guard_ceo()` in `routes/users.py`) — never
  a tier/department change, never deactivated/deleted, checked at the
  route layer so it can't be bypassed by calling a lower-level function
  directly. Every other tier/department change is checked against
  `services/permissions.can_create_tier()` — CEO creates/manages
  anyone; Head Manager creates/manages Department Manager, Checker and
  Maker in any department but not another Head Manager; a Department
  Manager creates/manages only Checker and Maker within their own
  department.
- Verification and password-reset tokens (itsdangerous, signed with
  `JWT_SECRET_KEY`) expire on a configurable TTL
  (`VERIFICATION_TOKEN_TTL_HOURS`, `PASSWORD_RESET_TTL_MINUTES`); an
  expired token returns `{"expired": true}` so the frontend can offer a
  fresh link instead of a bare error.

## 7. Deployment

- `docker-compose.yml` at project root, one service per container in §2.
- **The browser never sees the backend's own host or port.** The
  frontend's `lib/api.js` calls a plain relative `/api/*` (its
  `BASE_URL` defaults to `""`). The frontend's own Nitro server (a
  Node process — see `vite.config.ts`'s `nitro.routeRules`) proxies
  `/api/**` to the backend container (`http://backend:5000` inside the
  Docker network, configurable via `BACKEND_INTERNAL_URL`, a build arg
  in `frontend/Dockerfile`). This is what fixed the "Unable to connect
  to the API at http://localhost:5000" error on the set-password page:
  the old hardcoded URL only ever resolved on whatever machine
  happened to be running the backend, never on a visitor's own machine
  in production, and could differ from the frontend's own host
  (`localhost` vs `127.0.0.1` vs a VPS domain) even in development.
- `email-service` has a Docker healthcheck (any HTTP response from
  `index.php` counts — proves Apache/PHP are actually serving requests,
  not just that the container process has started), and `backend`'s
  `depends_on` waits on `condition: service_healthy` for it. Plain
  `depends_on` (the previous setup) only guarantees container START
  order, not readiness — a real race existed where the backend could
  handle its first "create user" request, and fire its first
  verification email, before email-service had finished coming up, and
  that failed send was silently discarded (fixed separately in
  `services/accounts.py` — see §3's `send_email_async`).
- Coolify manages builds/redeploys on push to `main`, via GitHub Actions
  running the pytest suite first — deploy only triggers on green tests.
- Environment variables (`.env`, never committed) hold all secrets: DB
  credentials, JWT secret, SMTP credentials, internal service secret,
  and the token TTLs above.
- Phase 6 adds `docker-compose.prod.yml` — the file Coolify actually
  deploys, distinct from `docker-compose.yml` (local/dev). Only the
  `frontend` service is reachable at all (`expose`, never `ports:`);
  Coolify's own proxy terminates HTTPS and attaches the domain to it on
  port 3000. The backend's container runs migrations and the idempotent
  CEO seed before serving (`backend/docker-entrypoint.prod.sh`) —
  unattended, since the dev compose file's manual
  `docker compose exec backend ...` procedure (`DEPLOYMENT.md`) assumes
  someone is there to run them by hand, which nothing is in a Coolify
  deploy. See `DEPLOYMENT.md` for the full environment-variable
  checklist and backup/restore/rollback procedure.
- `GET /api/health` (used by the healthcheck above and by Coolify) runs
  `SELECT 1` against the database, not just a bare 200 — a backend that's
  up but can't reach Postgres should be restarted, not kept serving.

### 7a. Backups (Phase 6)

- A CEO/head_manager's interactive download (`routes/backup.py`, Backup
  page) is a `pg_dump` + uploads zip, AES-256-GCM encrypted with a
  password typed at download time — never stored, never logged, held
  only for that one request. `services/backup.py` has the encrypt/
  decrypt/dump/restore logic; `scripts/restore_backup.py` is the CLI
  that reverses it (destructive, gated behind `--yes`).
- An unattended nightly job (`services/scheduler.py`'s
  `run_nightly_backup`, 2am) writes the same dump+uploads zip
  **unencrypted** to a dedicated `backups` volume, kept 14 days
  (`BACKUP_RETENTION_DAYS`) — there's no one present to supply a
  password for it, so it relies on the container/volume's own access
  control instead of a stored key. `backup_logs` (one row per backup,
  either kind) is what the Backup page's status and the dashboard's
  "no download in 7+ days" warning both read.
- `pg_dump`/`psql` are pinned to major version 15 in `backend/Dockerfile`
  (the official PGDG apt repo, not Debian's own default package, which
  resolves to v18 and writes a dump preamble a v15 server's `psql`
  rejects outright on restore — found and fixed by actually running the
  dump→encrypt→decrypt→restore cycle against a real Postgres 15
  container, not assumed).

## 8. Security Hardening (Phase 2)

- **Startup safety** (`services/startup_safety.py`): `create_app()`
  computes `ENVIRONMENT` (`development` | `production` | `testing`)
  and refuses to start in anything but `development` if debug mode is
  requested, or if `JWT_SECRET_KEY`, the database password, or
  `EMAIL_SERVICE_SECRET` is missing, under 32 bytes, or a known
  placeholder. `Dockerfile`'s `CMD` runs gunicorn (2 workers), never
  `python app.py`. `docker-compose.yml` reads every secret from `.env`
  via Compose's `${VAR:?message}` required-variable syntax — there is
  no second line of defense needed at that layer, but there is one
  anyway.
- **CEO seed** (`seed_ceo.py`, `services/password_policy.py`):
  `CEO_EMAIL`/`CEO_PASSWORD` have no fallback; the password is checked
  against the same `validate_password_strength()` the mandatory
  change-password endpoint uses (≥12 chars, not an obvious value). The
  seeded (or reset) CEO carries `must_change_password=True`, enforced
  by an endpoint allowlist inside `auth_required()` — every other
  endpoint 403s until `POST /api/auth/change-password` succeeds.
- **Row locking + optimistic versioning** (`routes/operations.py`,
  `routes/payroll.py`): `decide_record()`, `decide_leave()`,
  `reverse_penalty()`, `create_repayment()`, `settle_loan()`, and
  payroll's `finalize_batch()`/`cancel_batch()` all fetch their target
  row with `.with_for_update()` — on Postgres this blocks a second
  concurrent request until the first commits. `Loan`, `Penalty`,
  `LeaveRequest`, and `PayrollBatch` additionally carry a `lock_version`
  column (`__mapper_args__ = {"version_id_col": ...}`), so SQLAlchemy
  stamps `WHERE lock_version = <current>` on every UPDATE and raises
  `StaleDataError` if another transaction already changed the row —
  this is what makes "never applies twice" true even on a database
  (e.g. SQLite in tests) that doesn't honor `FOR UPDATE`. A caught
  `StaleDataError` resolves to `already_handled_response()` (the same
  record was decided elsewhere) or a generic `retry_conflict_response()`
  (a different row — e.g. the same loan's balance — moved instead).
- **Repayment idempotency**: `repayments.idempotency_key` (nullable,
  unique) — `create_repayment()`/`settle_loan()` look up an existing
  row by the submitted key before doing any work and return it as a
  replay (`200`, not `201`) instead of recording a second payment; a
  genuinely concurrent duplicate is caught by the unique constraint
  (`IntegrityError`) and resolved the same way.
- **Rate limiting** (`services/rate_limit.py`,
  `models/rate_limit.py`'s `RateLimitAttempt`): a DB-backed counter per
  `(scope, identifier)` — `identifier` is `ip:<addr>` and, where an
  email was submitted, also `email:<address>` — so a lockout is both
  per-account and per-IP, and holds across every gunicorn worker
  process (unlike an in-memory counter). Applied to `/api/auth/login`,
  `/resend-verification`, `/password-reset/request`,
  `/password-reset/validate`, and `/password-reset/confirm`. Every
  response stays generic regardless of which bucket tripped it or
  whether the account exists.
- **Security headers**: the backend's `app.py` sets CSP
  (`default-src 'none'`, since the API only ever serves JSON/files),
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, `Permissions-Policy`, and HSTS when
  the request arrived over HTTPS (directly or via
  `X-Forwarded-Proto`). The frontend's `vite.config.ts` sets the same
  set via Nitro `routeRules["/**"].headers`, with a page-appropriate
  CSP (`'self'` plus `'unsafe-inline'` on `script-src`/`style-src` —
  required by TanStack Start's own SSR hydration script and a few
  inline `style={{}}` usages; `blob:` on `img-src` for
  `URL.createObjectURL()` photo/logo previews).
- **Borrower file access**: `GET /api/borrowers/<id>/<kind>` (photo,
  ID document) is gated behind
  `borrowers:view`/`borrowers:manage` (previously `@auth_required`
  only — any logged-in account, including an HR/Finance
  department_manager, could download it) and writes an audit entry on
  every download.
- **Migration 20260921_0003** (email became mandatory) now backfills
  any pre-existing NULL email with a synthetic, unique placeholder
  (`legacy-user-<id>@placeholder.invalid`) before tightening the
  column to `NOT NULL` — it previously failed outright on a database
  with any user row created before this migration. Its two
  `alter_column` calls run inside `batch_alter_table()` so the
  migration can also be exercised against SQLite (see
  `tests/test_migration_email_backfill.py`); behavior against Postgres
  is unchanged.
- **Indexes** (migration `20261011_0019`): added on every foreign key
  and status/date column filtered constantly and never indexed before
  (Postgres does not index foreign keys automatically) — `loans`
  (`borrower_id`, `loan_product_id`, `start_date`, `status`),
  `payment_schedules` (`loan_id`, `due_date`), `repayments` (`loan_id`,
  `schedule_id`, `payment_date`), `penalties` (`loan_id`, `status`,
  `date_applied`), `audit_logs` (`user_id`, `timestamp`), plus
  `leave_requests`, `payroll_runs`, `assets`, `expenses`, and
  `capital_entries`.
