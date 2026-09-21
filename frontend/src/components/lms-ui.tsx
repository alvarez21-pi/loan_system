/** Small presentational kit shared by every screen. */
import type { ReactNode } from "react";

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
  approved: "lms-badge-info",
  active: "lms-badge-success",
  closed: "lms-badge-neutral",
  paid: "lms-badge-success",
  rejected: "lms-badge-danger",
  overdue: "lms-badge-danger",
};

export function StatusBadge({ status }: { status?: unknown }) {
  const key = String(status || "unknown")
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
  const variant = STATUS_STYLES[key] || "lms-badge-neutral";
  return <span className={`lms-badge ${variant}`}>{key.replace(/_/g, " ")}</span>;
}

export function Field({
  label,
  error,
  children,
  hint,
}: {
  label: ReactNode;
  error?: string | undefined;
  children?: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div>
      <label className="lms-label">{label}</label>
      {children}
      {hint && !error ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      {error ? <p className="lms-error">{error}</p> : null}
    </div>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`lms-input ${props.className || ""}`} />;
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
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: string }) {
  return (
    <button {...props} type={type} className={`lms-btn lms-btn-${variant} ${props.className || ""}`}>
      {children}
    </button>
  );
}

export type Column = {
  key: string;
  label: ReactNode;
  render?: (row: any) => ReactNode;
};

export function DataTable({
  columns,
  rows,
  empty = "No records yet.",
}: {
  columns: Column[];
  rows: any[];
  empty?: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="lms-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key}>{c.label}</th>
            ))}
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
              <tr key={row?.id ?? i}>
                {columns.map((c) => (
                  <td key={c.key}>{c.render ? c.render(row) : (row?.[c.key] ?? "—")}</td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "warning" | "danger" | "success";
  children?: ReactNode;
}) {
  const tones = {
    info: "lms-badge-info",
    warning: "lms-badge-warning",
    danger: "lms-badge-danger",
    success: "lms-badge-success",
  };
  if (!children) return null;
  return (
    <div
      className={`lms-badge ${tones[tone]} mb-4 block w-full rounded-md px-3 py-2 text-left text-xs normal-case tracking-normal`}
    >
      {children}
    </div>
  );
}

export const money = (value: unknown) =>
  value === null || value === undefined || value === ""
    ? "—"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(Number(value));
