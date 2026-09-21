import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import { Card, DataTable, Notice, PageHeader, StatCard, StatusBadge, money } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { auditLogs, borrowers, capital, errorMessage, loans } from "../lib/api";

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
  const b = useResource(() => borrowers.list(), []);
  const l = useResource(() => loans.list(), []);
  const a = useResource(() => auditLogs.list(), []);
  const [capitalSummary, setCapitalSummary] = useState<any>(null);
  const [capitalError, setCapitalError] = useState("");
  useEffect(() => { capital.summary().then(setCapitalSummary).catch((error) => setCapitalError(errorMessage(error))); }, []);

  const loanRows = l.data || [];
  const active = loanRows.filter((x: any) => String(x.status).toLowerCase() === "active").length;
  const pending = loanRows.filter((x: any) =>
    PENDING.includes(String(x.status).toLowerCase().replace(/[\s-]+/g, "_")),
  ).length;
  const outstanding = loanRows.reduce(
    (sum: number, x: any) => sum + Number(x.outstanding_balance ?? x.balance ?? 0),
    0,
  );

  return (
    <>
      <PageHeader title="Dashboard" description="Live portfolio position across the branch." />
        <Notice tone="danger">{capitalError}</Notice>
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">{["cash_capital", "total_asset_value", "currently_lent_out", "total_collected", "available_to_lend"].map((key) => <StatCard key={key} label={key.replace(/_/g, " ")} value={money(capitalSummary?.[key])} />)}</div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total borrowers" value={(b.data || []).length} />
        <StatCard label="Active loans" value={active} />
        <StatCard label="Pending approvals" value={pending} hint="Loans awaiting a checker" />
        <StatCard label="Outstanding balance" value={money(outstanding)} />
      </div>

      <div className="mt-6 grid gap-4 xl:grid-cols-2">
        <Card title="Recent loans">
          <DataTable
            rows={loanRows.slice(0, 6)}
            columns={[
              { key: "id", label: "Loan" },
              { key: "borrower_name", label: "Borrower", render: (r: any) => r.borrower_name || r.borrower?.name || "—" },
              { key: "principal_amount", label: "Principal", render: (r: any) => money(r.principal_amount) },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
            ]}
          />
        </Card>
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
      </div>
    </>
  );
}
