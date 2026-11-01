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
        {([["Payments due in the next 7 days", notices.due_soon || [], false], ["Overdue payments", notices.overdue || [], true], ["Loans closing soon", notices.closing_soon || [], false]] as any[]).map(([title, rows, urgent]) => (
          <Card key={title} title={title}>
            {rows.length ? rows.map((item: any, index: number) => <div key={`${item.loan_id}-${item.due_date}-${index}`} className={`border-b py-2 text-sm ${urgent ? "text-red-700" : ""}`}>
              <Link to="/loans/$id" params={{ id: String(item.loan_id) }} className="font-medium underline">{item.borrower_name} · {item.reference}</Link>
              <div>{money(item.amount_due)} · {item.due_date} · {urgent ? `${Math.abs(item.days)} days overdue` : `${item.days} days remaining`}</div>
            </div>) : <p className="text-sm text-muted-foreground">None</p>}
          </Card>
        ))}
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
