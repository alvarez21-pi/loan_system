/** Small presentational kit shared by every screen. */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { dismissToast, subscribeToasts } from "../lib/toast";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions}
    </div>
  );
}

export function Card({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`lms-card ${className}`}>
      {title ? (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">{title}</h2>
            {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
          </div>
          {actions}
        </header>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

/**
 * A self-contained modal dialog — for an action that deserves an
 * unambiguous, focused interaction (e.g. editing a user) rather than content
 * silently appearing elsewhere on the page (Part 7). Closes on Escape or a
 * backdrop click; the page behind it never scrolls while it's open.
 */
const MODAL_WIDTHS = { sm: "max-w-sm", md: "max-w-md", lg: "max-w-2xl" };

export function Modal({
  title,
  description,
  onClose,
  children,
  size = "md",
  wide = false,
}: {
  title: ReactNode;
  description?: ReactNode;
  onClose: () => void;
  children?: ReactNode;
  /** Phase 5: three fixed widths — sm/md/lg. */
  size?: "sm" | "md" | "lg";
  /** @deprecated use size="lg" instead. */
  wide?: boolean;
}) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className={`lms-card lms-overlay-shadow max-h-[85vh] w-full overflow-y-auto sm:max-h-[90vh] ${MODAL_WIDTHS[wide ? "lg" : size]}`}>
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">{title}</h2>
            {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
          </div>
          <button type="button" aria-label="Close" className="lms-btn lms-btn-outline px-2 py-1 text-xs" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

const TOAST_TONE_CLASS: Record<string, string> = {
  success: "lms-toast-success",
  danger: "lms-toast-danger",
  warning: "lms-toast-warning",
  info: "lms-toast-info",
};

/** Small inline icon per tone — plain SVG, no icon library (Part 12). */
function ToastIcon({ tone }: { tone: string }) {
  const common = { width: 18, height: 18, viewBox: "0 0 20 20", fill: "none", "aria-hidden": "true" as const };
  if (tone === "success") {
    return (
      <svg {...common}>
        <circle cx="10" cy="10" r="9" fill="currentColor" opacity="0.18" />
        <path d="M6 10.3l2.4 2.4L14.5 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (tone === "danger") {
    return (
      <svg {...common}>
        <circle cx="10" cy="10" r="9" fill="currentColor" opacity="0.18" />
        <path d="M7 7l6 6M13 7l-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (tone === "warning") {
    return (
      <svg {...common}>
        <path d="M10 2.5l8 14.5H2L10 2.5z" fill="currentColor" opacity="0.18" />
        <path d="M10 8v4.2M10 15h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="10" cy="10" r="9" fill="currentColor" opacity="0.18" />
      <path d="M10 9.2v4.3M10 6.7h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * Floating toast stack, outside the page's normal layout flow (Part 12) —
 * mounted once, in AppShell, never reserves space when empty. Bottom-center
 * on phones, bottom-right on desktop (the `sm:` breakpoint used elsewhere in
 * the shared kit, e.g. SearchInput). Success/info auto-dismiss; danger/
 * warning stay until the user closes them (lib/toast.js), so every toast
 * also gets an explicit close button rather than relying on "click
 * anywhere."
 */
type Toast = { id: number; message: string; tone: string; link?: { label: string; to: string } | null };

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(() => subscribeToasts(setToasts), []);
  if (!toasts.length) return null;
  return (
    <div
      aria-live="polite"
      aria-atomic="true"
      // Sits above any page-local sticky bottom action bar (Part 14 phone
      // pass): a page with one sets --mobile-bottom-bar-h on <html> while it's
      // mounted (see useStickyBottomBar in lms-ui.tsx), which this adds on top
      // of the usual safe-area inset; pages without one leave it at 0.
      className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4 sm:inset-x-auto sm:right-4 sm:items-end"
      style={{ paddingBottom: "calc(env(safe-area-inset-bottom, 0px) + var(--mobile-bottom-bar-h, 0px))" }}
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role={t.tone === "danger" || t.tone === "warning" ? "alert" : "status"}
          className={`lms-toast ${TOAST_TONE_CLASS[t.tone] || TOAST_TONE_CLASS.success} lms-overlay-shadow pointer-events-auto flex w-full max-w-md items-start gap-2 rounded-md px-3 py-2.5 text-sm normal-case tracking-normal`}
        >
          <span className="mt-0.5 shrink-0">
            <ToastIcon tone={t.tone} />
          </span>
          <span className="min-w-0 flex-1">
            {t.message}
            {t.link ? (
              <Link
                to={t.link.to}
                onClick={() => dismissToast(t.id)}
                className="ml-2 inline-block shrink-0 whitespace-nowrap font-semibold underline"
              >
                {t.link.label}
              </Link>
            ) : null}
          </span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => dismissToast(t.id)}
            className="shrink-0 rounded-md p-0.5 opacity-80 hover:opacity-100"
          >
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  );
}

/**
 * A page with a phone-only sticky bottom action bar (loan detail, the
 * repayment form, the settlement form) calls this with `true` while mounted
 * so the floating toast stack (above) raises itself clear of that bar instead
 * of overlapping it, and resets it back to 0 on unmount. `barHeightPx`
 * defaults to the standard sticky bar height used across the app.
 */
export function useMobileBottomBarOffset(active: boolean, barHeightPx = 64) {
  useEffect(() => {
    if (!active) return;
    const root = document.documentElement;
    const previous = root.style.getPropertyValue("--mobile-bottom-bar-h");
    root.style.setProperty("--mobile-bottom-bar-h", `${barHeightPx}px`);
    return () => {
      if (previous) root.style.setProperty("--mobile-bottom-bar-h", previous);
      else root.style.removeProperty("--mobile-bottom-bar-h");
    };
  }, [active, barHeightPx]);
}

export function StatCard({
  label,
  value,
  hint,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="lms-card p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

const STATUS_STYLES: Record<string, string> = {
  draft: "lms-badge-neutral",
  pending: "lms-badge-warning",
  pending_approval: "lms-badge-warning",
  submitted: "lms-badge-warning",
  // Phase 5: status colours are a closed set of four (green=positive,
  // amber=pending, red=problem, grey=closed) — "approved" is a positive
  // outcome, so it gets the same green as "active" rather than a fifth
  // (blue) hue outside that set.
  approved: "lms-badge-success",
  active: "lms-badge-success",
  closed: "lms-badge-neutral",
  paid: "lms-badge-success",
  partial: "lms-badge-warning",
  rejected: "lms-badge-danger",
  reversed: "lms-badge-danger",
  overdue: "lms-badge-danger",
  missed: "lms-badge-danger",
  late: "lms-badge-danger",
  upcoming: "lms-badge-neutral",
  inactive: "lms-badge-neutral",
  cancelled: "lms-badge-neutral",
  recorded: "lms-badge-success",
  verified: "lms-badge-success",
  unverified: "lms-badge-neutral",
};

/** Plain-language status labels — DESIGN.md section 7. Borrowers and staff see
 * this, never the raw database enum value. */
export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  pending: "Waiting for approval",
  pending_approval: "Waiting for approval",
  submitted: "Waiting for approval",
  approved: "Approved",
  active: "Active",
  closed: "Fully paid",
  rejected: "Rejected",
  reversed: "Reversed",
  paid: "Paid",
  partial: "Partially paid",
  missed: "Payment missed",
  late: "Late",
  upcoming: "Upcoming",
  overdue: "Overdue",
  cancelled: "Cancelled",
  recorded: "Recorded",
};

export function statusLabel(status?: unknown, reason?: string | null) {
  const key = String(status || "unknown")
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
  const label = STATUS_LABELS[key] || key.replace(/_/g, " ");
  if (key === "rejected" && reason) return `${label} — ${reason}`;
  return label;
}

export function StatusBadge({ status, reason }: { status?: unknown; reason?: string | null }) {
  const key = String(status || "unknown")
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
  const variant = STATUS_STYLES[key] || "lms-badge-neutral";
  return <span className={`lms-badge ${variant}`}>{statusLabel(status, reason)}</span>;
}

const BADGE_TO_LABEL_TONE: Record<string, string> = {
  "lms-badge-neutral": "lms-status-label-neutral",
  "lms-badge-info": "lms-status-label-neutral",
  "lms-badge-warning": "lms-status-label-warning",
  "lms-badge-success": "lms-status-label-success",
  "lms-badge-danger": "lms-status-label-danger",
};

/**
 * A restrained alternative to StatusBadge for a dense account list (Users,
 * Employees — Part 6.1): a small plain-text label instead of a large
 * coloured pill. Same status vocabulary/colors, just not a pill.
 */
export function StatusLabel({ status, reason }: { status?: unknown; reason?: string | null }) {
  const key = String(status || "unknown")
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
  const tone = BADGE_TO_LABEL_TONE[STATUS_STYLES[key] || "lms-badge-neutral"];
  return <span className={`lms-status-label ${tone}`}>{statusLabel(status, reason)}</span>;
}

/**
 * A restrained row action — a small text link, not a full button, for a
 * dense account list (Part 6.1).
 */
export function TextLink({
  onClick,
  disabled,
  children,
  tone,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
  tone?: "danger";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`lms-text-link ${tone === "danger" ? "lms-text-link-danger" : ""}`}
    >
      {children}
    </button>
  );
}

export function Field({
  label,
  error,
  children,
  hint,
  name,
}: {
  label: ReactNode;
  error?: string | undefined;
  children?: ReactNode;
  hint?: ReactNode;
  /** Matches this field's key in a form's `errors` map, so
   * `scrollToFirstError()` can find and highlight it (Part 6.3). */
  name?: string;
}) {
  return (
    <div data-field={name}>
      <label className="lms-label">{label}</label>
      {children}
      {hint && !error ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      {error ? <p className="lms-error">{error}</p> : null}
    </div>
  );
}

/**
 * On a failed form submission, the error is shown as a floating toast (so
 * it's never stuck off-screen above a long form) AND the first invalid
 * field is scrolled into view and briefly highlighted (Part 6.3). `errors`
 * is the same {fieldKey: message} map passed to each Field's `error` prop;
 * fields opt in with a matching `name`.
 */
export function scrollToFirstError(errors: Record<string, string | undefined>) {
  const firstKey = Object.keys(errors).find((k) => errors[k]);
  if (!firstKey) return;
  if (typeof document === "undefined") return;
  const el = document.querySelector(`[data-field="${firstKey}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("lms-field-highlight");
  setTimeout(() => el.classList.remove("lms-field-highlight"), 2000);
}

/**
 * An "Edit" button whose form lives lower on the page (e.g. deduction types,
 * loan products, employees, users) silently does nothing visible near the
 * click otherwise — the user has to notice a form changed further down on
 * their own. Attach the returned `ref` to the form's own container and call
 * this with whatever value identifies "currently editing" (an id, or the
 * row object itself) — whenever it changes from empty/falsy to a real value,
 * the container smoothly scrolls into view and the first focusable field
 * inside it receives focus, once the DOM has actually rendered it.
 */
export function useScrollIntoViewOnChange<T extends HTMLElement = HTMLDivElement>(trigger: unknown) {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (!trigger) return;
    const raf = requestAnimationFrame(() => {
      const el = ref.current;
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      const field = el.querySelector<HTMLElement>("input, select, textarea");
      field?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger]);
  return ref;
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`lms-input ${props.className || ""}`} />;
}

/** Thousand-separated display of a plain numeric string: "1234567.5" -> "1,234,567.5". */
function withThousands(raw: string) {
  if (raw === "") return "";
  const [whole = "", frac] = raw.split(".");
  const withCommas = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return frac !== undefined ? `${withCommas}.${frac}` : withCommas;
}

/**
 * The one numeric input for the whole app. Formats with thousand separators
 * as the user types (1,000,000), physically blocks the minus / exponent keys,
 * strips anything that is not a digit (so pasted text is cleaned too) and
 * reports the plain numeric value (a string, no commas) via onValueChange —
 * never negative, never non-numeric. Use this for EVERY number a user types
 * (money, rates, terms, ids) instead of `<Input type="number">`.
 *
 * decimals: max digits after the point (default 2). integer: whole numbers only.
 */
export function NumberInput({
  value,
  onValueChange,
  placeholder,
  className = "",
  decimals = 2,
  integer = false,
  ...rest
}: {
  value: string | number;
  onValueChange: (raw: string) => void;
  placeholder?: string;
  className?: string;
  decimals?: number;
  integer?: boolean;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type">) {
  const ref = useRef<HTMLInputElement>(null);
  const caret = useRef<number | null>(null);
  const formatted = withThousands(String(value ?? ""));

  function clean(text: string) {
    const digitsOnly = text.replace(integer ? /[^0-9]/g : /[^0-9.]/g, "");
    const firstDot = digitsOnly.indexOf(".");
    if (firstDot === -1) return digitsOnly.replace(/^0+(?=\d)/, "");
    const whole = digitsOnly.slice(0, firstDot).replace(/^0+(?=\d)/, "") || "0";
    const frac = digitsOnly.slice(firstDot + 1).replace(/\./g, "").slice(0, decimals);
    return decimals === 0 ? whole : `${whole}.${frac}`;
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const el = e.target;
    // Remember how many number characters sit left of the caret so it can be
    // put back in the same place after the commas are re-inserted.
    caret.current = el.value.slice(0, el.selectionStart ?? el.value.length).replace(/[^0-9.]/g, "").length;
    onValueChange(clean(el.value));
  }

  useLayoutEffect(() => {
    const el = ref.current;
    if (caret.current === null || !el || document.activeElement !== el) return;
    let seen = 0;
    let pos = caret.current === 0 ? 0 : el.value.length;
    for (let i = 0; i < el.value.length && caret.current > 0; i++) {
      if (/[0-9.]/.test(el.value.charAt(i))) seen++;
      if (seen === caret.current) {
        pos = i + 1;
        break;
      }
    }
    el.setSelectionRange(pos, pos);
    caret.current = null;
  }, [formatted]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (["-", "+", "e", "E", "Minus", "Subtract"].includes(e.key)) e.preventDefault();
  }

  return (
    <input
      {...rest}
      ref={ref}
      type="text"
      // A phone shows the plain numeric keypad for a whole-number field
      // (every money field is now whole shillings, decimals=0) and the
      // decimal keypad only when digits after the point are actually allowed.
      inputMode={integer || decimals === 0 ? "numeric" : "decimal"}
      autoComplete="off"
      value={formatted}
      placeholder={placeholder}
      onChange={handleChange}
      onKeyDown={handleKeyDown}
      className={`lms-input ${className}`}
    />
  );
}

/** Money field: NumberInput with two decimals. Kept as its own name for readability at call sites. */
export function MoneyInput(props: React.ComponentProps<typeof NumberInput>) {
  // Every money amount is a whole shilling now (Part 1.3) - no decimals to type.
  return <NumberInput decimals={0} {...props} />;
}

export function Checkbox({
  label,
  checked,
  onChange,
  hint,
  disabled,
}: {
  label: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-start gap-2 text-sm">
      <input
        type="checkbox"
        className="mt-1"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        {label}
        {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      </span>
    </label>
  );
}

/** The one search box for a list page (Phase 5) — plain text, no icon decoration beyond the placeholder. */
export function SearchInput({
  value,
  onChange,
  placeholder = "Search...",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <input
      type="search"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      aria-label={placeholder}
      className="lms-input w-full sm:w-64"
    />
  );
}

/**
 * Page controls for a server-paginated list (Phase 5) — wire directly to
 * `usePaginatedResource`'s `page`/`pagination`/`setPage`. Hidden when there's
 * only one page, so it never reserves space on a short list.
 */
export function Pagination({
  page,
  pagination,
  onPageChange,
}: {
  page: number;
  pagination: { page: number; page_size: number; total: number; total_pages: number } | null;
  onPageChange: (page: number) => void;
}) {
  if (!pagination || pagination.total_pages <= 1) return null;
  const { total, total_pages, page_size } = pagination;
  const from = (page - 1) * page_size + 1;
  const to = Math.min(page * page_size, total);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-sm text-muted-foreground">
      <span>
        {from}–{to} of {fmtNumber(total, 0)}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="secondary" compact disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          Previous
        </Button>
        <span>
          Page {page} of {total_pages}
        </span>
        <Button variant="secondary" compact disabled={page >= total_pages} onClick={() => onPageChange(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  );
}

/**
 * Shared loading / error / empty states for a list page (Phase 5) — a plain
 * row inside the table area, not a separate layout, so the card never jumps.
 */
export function ListStatus({
  loading,
  error,
  empty,
  emptyMessage = "No records yet.",
}: {
  loading: boolean;
  error?: string;
  empty: boolean;
  emptyMessage?: ReactNode;
}) {
  if (loading) return <p className="px-4 py-6 text-center text-sm text-muted-foreground">Loading…</p>;
  if (error) return <InlineNote tone="danger">{error}</InlineNote>;
  if (empty) return <p className="px-4 py-6 text-center text-sm text-muted-foreground">{emptyMessage}</p>;
  return null;
}

export function Select({
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...props} className={`lms-input ${props.className || ""}`}>
      {children}
    </select>
  );
}

export function Button({
  variant = "primary",
  type = "button",
  compact = false,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: string; compact?: boolean }) {
  return (
    <button
      {...props}
      type={type}
      className={`lms-btn lms-btn-${variant} ${compact ? "lms-btn-compact" : ""} ${props.className || ""}`}
    >
      {children}
    </button>
  );
}

export type Column = {
  key: string;
  label: ReactNode;
  render?: (row: any) => ReactNode;
  /** Column can be sorted via the shared list hook (Phase 5). */
  sortKey?: string;
};

/** Default cell: numbers always go through the shared formatter. Reference ids stay plain. */
function cell(key: string, value: unknown): ReactNode {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return key === "id" || key.endsWith("_id") ? String(value) : fmtNumber(value);
  return value as ReactNode;
}

/** A column is numeric (right-aligned, Phase 5) unless it's an id/reference column. */
function isNumericColumn(col: Column, rows: any[]): boolean {
  if (col.render) return false;
  if (col.key === "id" || col.key.endsWith("_id")) return false;
  return rows.some((row) => typeof row?.[col.key] === "number");
}

export function DataTable({
  columns,
  rows,
  empty = "No records yet.",
  totalsRow,
  onRowClick,
  sort,
  order,
  onSort,
  mobileCard,
}: {
  columns: Column[];
  rows: any[];
  empty?: ReactNode;
  /** One cell per column — rendered as a bold row pinned below the last data
   * row (e.g. an amortization schedule's total payment/principal/interest).
   * Omitted, or hidden automatically, when there are no rows to total. */
  totalsRow?: ReactNode[] | undefined;
  /** When given, every row is clickable (whole row, Phase 5) and opens the record. */
  onRowClick?: (row: any) => void;
  /** Current sort column/direction plus a toggler — wire up to `usePaginatedResource` (Phase 5). */
  sort?: string | null;
  order?: "asc" | "desc";
  onSort?: (column: string) => void;
  /**
   * Phone pass: renders each row as a tappable card (below the `sm`
   * breakpoint) instead of a table row — a wide table is unreadable at
   * 360-412px even scrolled inside its own card. When omitted, the table
   * renders at every width exactly as before. The real `<table>` keeps
   * rendering at `sm:` and above either way (`hidden sm:block` /
   * `sm:hidden`), so nothing about desktop changes.
   */
  mobileCard?: (row: any) => ReactNode;
}) {
  const table = (
    <div className={`overflow-x-auto ${mobileCard ? "hidden sm:block" : ""}`}>
      <table className="lms-table">
        <thead>
          <tr>
            {columns.map((c) => {
              const numeric = isNumericColumn(c, rows);
              if (!c.sortKey || !onSort) {
                return (
                  <th key={c.key} className={numeric ? "lms-table-num" : ""}>
                    {c.label}
                  </th>
                );
              }
              const active = sort === c.sortKey;
              return (
                <th key={c.key} className={numeric ? "lms-table-num" : ""}>
                  <button
                    type="button"
                    onClick={() => onSort(c.sortKey as string)}
                    className="inline-flex items-center gap-1 uppercase tracking-wide"
                  >
                    {c.label}
                    {active ? <span aria-hidden="true">{order === "desc" ? "↓" : "↑"}</span> : null}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="text-center text-muted-foreground">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr
                key={row?.id ?? i}
                className={onRowClick ? "lms-row-clickable" : ""}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((c) => (
                  <td key={c.key} className={isNumericColumn(c, rows) ? "lms-table-num" : ""}>
                    {c.render ? c.render(row) : cell(c.key, row?.[c.key])}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
        {totalsRow && rows.length > 0 ? (
          <tfoot>
            <tr>
              {totalsRow.map((content, i) => (
                <td key={i}>{content}</td>
              ))}
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  );

  if (!mobileCard) return table;

  return (
    <>
      {table}
      <div className="space-y-2 sm:hidden">
        {rows.length === 0 ? (
          <p className="px-1 py-6 text-center text-sm text-muted-foreground">{empty}</p>
        ) : (
          rows.map((row, i) => (
            <div
              key={row?.id ?? i}
              className={`lms-card p-3 ${onRowClick ? "cursor-pointer" : ""}`}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              role={onRowClick ? "button" : undefined}
            >
              {mobileCard(row)}
            </div>
          ))
        )}
      </div>
    </>
  );
}


/**
 * A persistent inline message block — a full-page permission gate, a
 * load-failure where the data would otherwise sit, a hint that stays while a
 * form is being filled (Part 12/8.1: this is NOT the floating-toast pattern;
 * it's specifically for content that belongs in the page's own layout and
 * should stay visible, not a transient result of an action). Renders nothing
 * when there's no message, so it never reserves empty space (the bug that
 * used to show as an empty pale bar). Colors mirror .lms-badge's four tones
 * but sized for a block of text rather than a small inline label, and kept
 * as its own class so a redesign of the status-pill badge size elsewhere
 * never affects this.
 */
export function InlineNote({
  tone = "info",
  className = "",
  children,
}: {
  tone?: "info" | "warning" | "danger" | "success";
  className?: string;
  children?: ReactNode;
}) {
  if (!children) return null;
  return <div className={`lms-inline-note lms-inline-note-${tone} ${className}`}>{children}</div>;
}

/** Money: 1,234,567.89 (up to two decimals). Blank -> an em dash. */
export const money = (value: unknown) => {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "—";
  const amount = Number(value);
  // Part 1.5: every money amount is a whole shilling, displayed with commas
  // and NO decimals - a loan created before this change may still carry
  // cents in the database (left as-is, never backfilled); it simply
  // displays rounded here rather than crashing or showing stray decimals.
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(amount);
};

/** Any other number a user reads — counts, terms, rates: 12,000 / 25 / 12.5. */
export const fmtNumber = (value: unknown, maxDecimals = 2) =>
  value === null || value === undefined || value === "" || Number.isNaN(Number(value))
    ? "—"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: maxDecimals }).format(Number(value));

export const percent = (value: unknown) =>
  value === null || value === undefined || value === "" ? "—" : `${fmtNumber(value)}%`;
