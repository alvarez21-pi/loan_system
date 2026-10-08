# Design System (Phase 5)

The source of truth for every visual rule is `frontend/src/styles.css`
(the `@theme inline` block + `:root` tokens) and the shared components in
`frontend/src/components/lms-ui.tsx`. This document describes what those
two files encode, and the specific drift Phase 5 found and fixed. When
building a new page, use the components listed here instead of ad-hoc
Tailwind classes — that's what keeps this page from drifting again.

## 1. Color tokens

All colors are semantic oklch tokens on `:root`, mapped to Tailwind
utilities via `@theme inline` (e.g. `--color-primary: var(--primary)`).
**Never hardcode a color in a component** — use the Tailwind class
(`bg-primary`, `text-muted-foreground`, etc.) so a Company Settings
colour change (Phase 4) or a future theme change propagates everywhere.

- `background` / `foreground` — the page's own surface and text.
- `card` / `card-foreground` — every `.lms-card` (white, 1px border, **no
  shadow** — shadow is reserved for menus/modals only, see §3).
- `primary` / `primary-foreground` — the one accent color, overridden at
  runtime from Company Settings (`BrandingEffects.tsx`); navy is only the
  default a fresh install starts with.
- `muted` / `muted-foreground` — secondary text, table headers, hints.
- `success` / `warning` / `destructive` / `info` — tone backgrounds for
  badges, notices and toasts. `success`/`info` were darkened in Phase 5
  (0.55→0.5 and 0.58→0.52 lightness) because the white text on top only
  reached 4.45:1 / 4.15:1 contrast — both now clear 4.5:1 (see §7).
- **Status colors are a closed set of four**, independent of the
  tone-badge palette above: green = positive, amber = pending, red =
  problem, grey = closed (`STATUS_STYLES` in `lms-ui.tsx`). Phase 5 found
  one drift from this — `approved` was mapped to the blue `info` tone —
  and fixed it to green, since an approval is a positive outcome. Do not
  introduce a fifth hue into `STATUS_STYLES`.

## 2. Type scale, spacing scale, radius

- Font sizes used across the app: **12 / 14 / 16 / 20 / 24px**
  (`0.75rem` / `0.875rem` / `1rem` / `1.25rem` / `1.5rem`). Weights:
  **400 / 500 / 600** only.
- Spacing scale: **4 / 8 / 12 / 16 / 24 / 32px**. Phase 5 snapped several
  off-scale values to this (e.g. `.lms-label` margin `0.35rem`→`0.25rem`,
  `.lms-table` cell padding `0.6rem/0.85rem`→`0.5rem/0.75rem`,
  `.lms-nav-link` gap/padding `0.6rem`/`0.55rem 0.75rem`→`0.5rem`/`0.5rem
  0.75rem`).
- **One radius, 6px**, everywhere — inputs, buttons, cards, modals,
  badges (`--radius-md`, since `--radius: 0.5rem` i.e. 8px with the
  `calc(var(--radius) - 2px)` offset nets 6px). `.lms-card` was using
  `--radius-lg` (8px) before Phase 5; now `--radius-md`. `.lms-badge` was
  a true pill (`border-radius: 999px`) before Phase 5; now `--radius-md`
  — a small label, never a pill (§6).
- **One font family**, system-native:
  `ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial,
  sans-serif`. The previous declaration named `"IBM Plex Sans"` first,
  but no `<link>` or `@font-face` ever loaded that font (confirmed by
  grep — zero hits) — every browser was silently already falling back to
  this same system stack. Phase 5 just says so instead of naming an
  unloaded font.

## 3. Shadow

**One shadow, `--shadow-overlay`, reserved for menus and modals.** Cards
never have a shadow — a 1px border is the only surface separation. Before
Phase 5, `.lms-card` carried `box-shadow: var(--shadow-card)`; that
declaration is gone, and the token was renamed to `--shadow-overlay` and
applied only to `Modal`'s panel and the toast stack (`ToastContainer`,
which previously used a separate `shadow-lg` Tailwind utility — removed
in favor of the one shared token).

## 4. Buttons

`<Button>` (`lms-ui.tsx`) — variants `primary` / `secondary` / `outline`
(tertiary) / `destructive`. One height, **36px** (`.lms-btn`, explicit
`height: 2.25rem`, not an implicit height from padding as before). A
`compact` prop drops it to **30px** (`.lms-btn-compact`) for in-table
actions. No pills. Pass `disabled` while a submit is in flight — every
existing form already does this (`busy` state → `disabled={busy}`).

**Mobile tap targets**: below the sidebar's own collapse breakpoint
(767px and under), `.lms-btn` is forced to 40px regardless of the
`compact` prop, via a `@media (max-width: 767px)` override — the 36/30px
heights are deliberately a *desktop* density choice and would be
too small to reliably tap on a phone otherwise. Dense inline row actions
that are plain text links (`<TextLink>`, used in the Users table) are not
widened — enlarging every inline link in a dense list to 40px would
defeat the density they exist for; this is a deliberate exception, not an
oversight.

## 5. Tables

`<DataTable>` (`lms-ui.tsx`):

- Sticky header (`position: sticky; top: 0`) so a long list's column
  names stay visible while scrolling the card's own body.
- Numeric columns are automatically right-aligned with tabular figures
  (`.lms-table-num`, applied by `isNumericColumn()` — any column without
  a custom `render` whose values are numbers, excluding `id`/`*_id`
  columns). All existing number formatting already goes through
  `money()`/`fmtNumber()`/`percent()`, which add thousands separators.
- `onRowClick` makes the **whole row** clickable (cursor becomes a
  pointer via `.lms-row-clickable`) when a row opens a record — wired up
  on Borrowers, Loans and Repayments (each opens the relevant
  borrower/loan page). A link *inside* a clickable row (e.g. the
  Borrowers "View" button) calls `stopPropagation` so it doesn't also
  fire the row's own navigation. Users and Audit Logs have no detail
  page to open, so their rows are not clickable.
- `sort`/`order`/`onSort` wire a column's header into a clickable sort
  toggle (↑/↓ indicator) — pass `sortKey` on any `Column` that the
  backend's `paginate()` recognizes (see §8).
- Tables already scroll horizontally **inside their own card**
  (`overflow-x-auto` wrapper) rather than widening the page — this
  predates Phase 5 (`DESIGN.md` §10a) and still holds.
- Names, not raw ids: every table that references another record shows
  that record's name (`borrower_name`, `user`, etc.), never a bare
  foreign key. The one deliberate exception is the Audit Log's
  `record_id` column — audit rows span many different entity types
  (loans, users, borrowers, …), so resolving an id to a name generically
  would need per-entity lookups; the *actor* is already shown by name, and
  `record_id` is forensic detail, not the row's primary identity.

## 6. Status labels and badges

Two presentations of the same four-color status vocabulary
(`statusLabel()`/`STATUS_STYLES` in `lms-ui.tsx`):

- `<StatusBadge>` — a small label with a tinted background (not a pill —
  see §2), for a page where status is the primary thing being scanned
  (Loans, Repayments, Approvals).
- `<StatusLabel>` — plain colored text, no background, for a dense
  account list (Users, Employees) where a large badge per row would be
  visually heavier than the list needs (`DESIGN.md` §6e).

Neither is a true pill any more (see §2 — `border-radius: 999px` was
removed from `.lms-badge` in Phase 5).

## 7. Accessibility

- Text contrast was checked against WCAG AA (4.5:1 for normal text) by
  converting every foreground/background token pair's oklch values to
  linear sRGB and computing the standard relative-luminance contrast
  ratio. Two pairs failed and were fixed (§1): `success-foreground` on
  `success` (4.45:1 → 5.50:1) and `info-foreground` on `info` (4.15:1 →
  5.34:1). Every other pair in active use (body text, muted text, badges,
  the sidebar, buttons) already clears 4.5:1, most by a wide margin
  (`foreground` on `background` is 15.3:1).
- The focus ring (`--ring`, same hue as `--primary`) has a 5.6:1 contrast
  against the page background — clearly visible.
- **Known, not fixed**: the 1px border on cards/inputs (`--border` /
  `--input`) has very low contrast against the page background (~1.3:1),
  well under WCAG's separate 3:1 non-text/UI-boundary guideline. This is
  a pre-existing "subtle border on a light surface" aesthetic choice
  (predates Phase 5), not something this phase's instructions asked to
  change, and inputs/buttons remain identifiable by their background
  fill and the focus ring once focused. Flagging it here rather than
  changing a visual choice that wasn't in scope — revisit if the design
  direction changes.
- Modals and menus are keyboard-usable: `Modal` closes on `Escape` and
  traps body scroll while open; the Employee form's Name/Phone fields had
  a hardcoded `tabIndex={1}`/`{2}` that broke the page's natural tab
  order (explicit positive `tabIndex`s are visited *before* every
  unindexed element in the whole document, not just within that form) —
  removed in Phase 5; the two fields' own adjacent position in the form's
  grid already gives the correct order without it.

## 8. Lists: search, sort, pagination

Every one of the five named lists (Borrowers, Loans, Repayments, Users,
Audit Log) uses the same pair of pieces:

- **Backend** — `backend/services/listing.py`'s `paginate(query, args,
  searchable=(), sortable={}, default_sort=None)`. Pagination is
  strictly **opt-in**: passing neither `page` nor `page_size` returns the
  full, unpaginated list exactly as before (no `pagination` key in the
  response) — this is what every other existing caller of these same
  endpoints (the dashboard, the approvals queue, a borrower's own loan
  history, the loans/borrowers pickers used when creating a new record)
  still gets, unchanged. Passing `page`/`page_size` returns a slice plus
  `{page, page_size, total, total_pages}`. `q` does a case-insensitive
  partial match across the `searchable` columns; `sort`/`order` pick one
  of the `sortable` columns.
- **Frontend** — `frontend/src/hooks/usePaginatedResource.js` owns
  `page`/`q` (debounced 300ms)/`sort`/`order` state and calls the loader
  whenever any of them change, resetting to page 1 on a filter/sort
  change. Pair it with `<SearchInput>`, `<Pagination>` and `<ListStatus>`
  (all in `lms-ui.tsx`) and `DataTable`'s `sort`/`order`/`onSort` props.
- A page that also needs the **full, unfiltered** list for something
  else on the same screen (Loans' pending-approval queue, Users' unlinked-
  employee picker, Audit Log's action-filter dropdown) loads that
  separately with the plain `useResource` hook, against the same
  endpoint called with no params — two independent loads of the same
  list, each for a different purpose. Audit Log's action dropdown has its
  own tiny endpoint, `GET /api/audit-logs/actions`, returning every
  distinct action value ever recorded (not just the current page's), so
  the options don't change as you page through; selecting one applies an
  **exact** server-side filter (`?action=...`), separate from the free-
  text `q` search.

## 9. Modals

`<Modal>` (`lms-ui.tsx`) takes `size: "sm" | "md" | "lg"` (default `md`).
`wide` (boolean) is kept as a deprecated alias for `size="lg"` for any
existing call site, but new code should pass `size`. Closes on `Escape`
or a backdrop click; every destructive/consequential action confirmed
through a modal or `window.confirm()` states the consequence in words
(e.g. the loan-approval confirmation spells out the amount, rate and term
before committing) rather than a bare "Are you sure?".

## 10. Animation

Transitions are capped at **150ms** (`transition: opacity 0.15s ease,
background-color 0.15s ease` on `.lms-btn`; Tailwind's `transition-colors`
utility defaults to the same 150ms). The one deliberate exception is
`.lms-field-highlight`'s 2-second flash — used once, to draw the eye to
the first invalid field after a failed form submission
(`scrollToFirstError()`, `DESIGN.md` §6f). A 150ms flash would be gone
before most people noticed it; this is a highlight-then-fade effect with
a different job than a routine hover/focus transition, not an
oversized version of one.

## 11. Icons

The app does not use an icon library or inline SVGs — every control is a
plain-language text button/link (`Save`, `Cancel`, `View`, `Edit`...).
The only non-text glyph is the modal close button's `✕`. There is
therefore no icon-set-consistency problem to fix; if icons are introduced
later, pick one set and one size and keep it to that.

## 12. Responsive behavior

Checked structurally (no browser was available in this environment, so
verification was manual/structural only):

- `AppShell`'s root is `overflow-hidden` with `overflow-x-hidden` on the
  one scrolling `<main>` region, and every flex child in that chain is
  `min-w-0` — the combination that lets a wide table scroll inside its
  own card (`DataTable`'s `overflow-x-auto` wrapper) instead of widening
  the page itself.
- The sidebar is `fixed` + hidden behind a "Menu" toggle below the `md`
  breakpoint (768px), and `static`/always-visible at `md` and above —
  this already covers 390px (collapsed) and 768/1366/1920px (fixed).
- Modals cap at `max-w-sm`/`max-w-md`/`max-w-2xl` with `max-h-[90vh]`
  and their own `overflow-y-auto`, so they fit within a 390px-tall mobile
  viewport rather than overflowing it.
- Button/tap-target sizing is covered in §4.
