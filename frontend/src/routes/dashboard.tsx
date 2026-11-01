import { createFileRoute, Link } from "@tanstack/react-router";
import AppShell from "../components/AppShell";
import { Card, DataTable, InlineNote, PageHeader, StatCard, StatusBadge, fmtNumber, money } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { auditLogs, backup, borrowers, capital, dashboard, getUser, hasPermission, loans } from "../lib/api";

export const Route = createFileRoute("/dashboard")({
  head: () => ({
    meta: [
      { title: "Dashboard — Microfinance LMS" },
      { name: "description", content: "Portfolio overview: borrowers, active loans, pending approvals and outstanding balance." },
      { property: "og:title", content: "Dashboard — Microfinance LMS" },
      { property: "og:description", content: "Portfolio overview and recent activity for loan operations." },
    ],
  }),
  component: () => (
    <AppShell>
      <DashboardPage />
    </AppShell>
  ),
});

const PENDING = ["pending", "pending_approval", "submitted"];

function groupByLoan(rows: any[]) {
  const groups = new Map<string, any[]>();
  for (const item of rows) {
    const key = String(item.loan_id);
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  return [...groups.values()]
    .map((items) => items.sort((a, b) => a.due_date.localeCompare(b.due_date)))
    .sort((a, b) => a[0].due_date.localeCompare(b[0].due_date));
}

function dueLabel(days: number) {
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  return `${days} days remaining`;
}

function DashboardPage() {
  const user = getUser();
  const canSeeAudit = hasPermission(user, "audit:view");
  const canSeeCapital = hasPermission(user, "capital:view");
  const canSeeBackup = hasPermission(user, "backup:manage");
  // Active only — a deactivated borrower shouldn't count toward this figure.
  const b = useResource(() => borrowers.list({ active_only: true }), []);
  const l = useResource(() => loans.list(), []);
  const noticeData = useResource(() => dashboard.summary(), []);
  const a = useResource(() => (canSeeAudit ? auditLogs.list() : Promise.resolve({ data: [] })), []);
  const capitalSummary = useResource(() => (canSeeCapital ? capital.summary() : Promise.resolve({ data: null })), []);
  const backupStatus = useResource(() => (canSeeBackup ? backup.status() : Promise.resolve({ data: null })), [canSeeBackup]);

  const loanRows = l.data || [];
  const active = loanRows.filter((x: any) => String(x.status).toLowerCase() === "active").length;
  const pending = loanRows.filter((x: any) =>
    PENDING.includes(String(x.status).toLowerCase().replace(/[\s-]+/g, "_")),
  ).length;
  const outstanding = loanRows.reduce(
    (sum: number, x: any) => sum + Number(x.outstanding_balance ?? x.balance ?? 0),
    0,
  );
  const cs: any = capitalSummary.data;
  const notices: any = (noticeData.data as any)?.notices || {};

  return (
    <>
      <PageHeader title="Dashboard" description="Live portfolio position across the branch." />
      {canSeeBackup && (backupStatus.data as any)?.stale ? (
        <InlineNote tone="warning">
          No backup has been downloaded in the last {(backupStatus.data as any)?.stale_after_days || 7} days.{" "}
          <Link to="/backup" className="underline">
            Download one from the Backup page
          </Link>
          .
        </InlineNote>
      ) : null}
      {/* Phone pass: 2 columns even below the `sm` breakpoint (360-412px),
          not stacked single-column, per the phone-first dashboard spec. */}
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard label="Active borrowers" value={fmtNumber((b.data || []).length)} />
        <StatCard label="Active loans" value={fmtNumber(active)} />
        <StatCard label="Pending approvals" value={fmtNumber(pending)} hint="Loans awaiting a checker" />
        <StatCard label="Outstanding balance" value={money(outstanding)} />
      </div>

      <div className="mt-6 grid gap-4 xl:grid-cols-3">
        <Card title="Payments due in the next 7 days">
          {groupByLoan(notices.due_soon || []).length ? groupByLoan(notices.due_soon || []).map((items) => {
            const next = items[0];
            const additional = items.slice(1);
            const additionalTotal = additional.reduce((sum, item) => sum + Number(item.amount_due), 0);
            return <div key={next.loan_id} className="border-b py-2 text-sm">
              <Link to="/loans/$id" params={{ id: String(next.loan_id) }} className="font-medium underline">{next.borrower_name} · {next.reference}</Link>
              <div>{money(next.amount_due)} · {next.due_date} · {dueLabel(next.days)}</div>
              {additional.length ? <div>+{additional.length} more this week ({money(additionalTotal)} combined)</div> : null}
            </div>;
          }) : <p className="text-sm text-muted-foreground">None</p>}
        </Card>
        <Card title="Overdue payments">
          {groupByLoan(notices.overdue || []).length ? groupByLoan(notices.overdue || []).map((items) => {
            const oldest = items[0];
            const total = items.reduce((sum, item) => sum + Number(item.amount_due), 0);
            const days = Math.abs(oldest.days);
            return <div key={oldest.loan_id} className="border-b py-2 text-sm text-red-700">
              <Link to="/loans/$id" params={{ id: String(oldest.loan_id) }} className="font-medium underline">{oldest.borrower_name} · {oldest.reference}</Link>
              <div>{items.length} overdue instalment{items.length === 1 ? "" : "s"}; total {money(total)}</div>
              <div>Oldest: {money(oldest.amount_due)} · {oldest.due_date} · {days} day{days === 1 ? "" : "s"} overdue</div>
            </div>;
          }) : <p className="text-sm text-muted-foreground">None</p>}
        </Card>
        <Card title="Loans closing soon">
          {(notices.closing_soon || []).length ? notices.closing_soon.map((item: any, index: number) => <div key={`${item.loan_id}-${item.due_date}-${index}`} className="border-b py-2 text-sm">
            <Link to="/loans/$id" params={{ id: String(item.loan_id) }} className="font-medium underline">{item.borrower_name} · {item.reference}</Link>
            <div>{money(item.amount_due)} · {item.due_date} · {dueLabel(item.days)}</div>
          </div>) : <p className="text-sm text-muted-foreground">None</p>}
        </Card>
      </div>
      {canSeeCapital ? (
        <div className="mt-6">
          <Card
            title="Capital"
            description="Read-only summary."
            actions={
              <Link to="/capital" className="lms-btn lms-btn-outline">
                Open Capital page
              </Link>
            }
          >
            <InlineNote tone="danger">{capitalSummary.error}</InlineNote>
            {cs && !cs.has_opening_entry ? (
              <InlineNote tone="warning">Opening capital has not been set yet.</InlineNote>
            ) : (
              <div className="grid grid-cols-2 gap-4 xl:grid-cols-5">
                <StatCard label="Cash on hand" value={money(cs?.cash_on_hand)} />
                <StatCard label="Outstanding Balance" value={money(cs?.outstanding_balance)} />
                <StatCard label="Total Disbursed" value={money(cs?.total_disbursed)} />
                <StatCard label="Assets value" value={money(cs?.assets_value)} />
                <StatCard label="Total worth" value={money(cs?.total_worth)} />
              </div>
            )}
          </Card>
        </div>
      ) : null}

      <div className="mt-6 grid gap-4 xl:grid-cols-2">
        <Card title="Recent loans">
          <DataTable
            rows={loanRows.slice(0, 6)}
            columns={[
              {
                key: "id",
                label: "Loan",
                render: (r: any) => (
                  <Link to="/loans/$id" params={{ id: String(r.id) }} className="text-primary underline">
                    #{r.id}
                  </Link>
                ),
              },
              { key: "borrower_name", label: "Borrower", render: (r: any) => r.borrower_name || "—" },
              { key: "principal_amount", label: "Principal", render: (r: any) => money(r.principal_amount) },
              { key: "dates", label: "Start / Closing", render: (r: any) => `${r.start_date || "—"} / ${r.closing_date || "—"}` },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
            ]}
          />
        </Card>
        {canSeeAudit ? (
          <Card title="Recent activity" description="Latest audit trail entries">
            <DataTable
              rows={(a.data || []).slice(0, 6)}
              columns={[
                { key: "user", label: "User", render: (r: any) => r.user || r.username || "—" },
                { key: "action", label: "Action" },
                { key: "table_name", label: "Table" },
                { key: "timestamp", label: "When", render: (r: any) => r.timestamp || r.created_at || "—" },
              ]}
            />
          </Card>
        ) : null}
      </div>
    </>
  );
}
