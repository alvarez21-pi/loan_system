import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import {
  Button,
  Card,
  DataTable,
  Notice,
  PageHeader,
  StatusBadge,
  money,
} from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { errorMessage, expenses, loans, payroll, penalties } from "../lib/api";

export const Route = createFileRoute("/approvals")({
  head: () => ({
    meta: [
      { title: "Approvals — Microfinance LMS" },
      { name: "description", content: "Approve or reject pending loans, expenses, payroll batches and penalties." },
      { property: "og:title", content: "Approvals — Microfinance LMS" },
      { property: "og:description", content: "Maker-checker approval queue for loans, expenses, payroll and penalties." },
    ],
  }),
  component: () => (
    <AppShell>
      <ApprovalsPage />
    </AppShell>
  ),
});

const PENDING = /pending|submitted|awaiting|review/i;
const isPending = (row: any) => PENDING.test(String(row.status || ""));

function ApprovalsPage() {
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [busyKey, setBusyKey] = useState("");

  const loanQueue = useResource(() => loans.list(), []);
  const expenseQueue = useResource(() => expenses.list(), []);
  const payrollQueue = useResource(() => payroll.list(), []);
  const penaltyQueue = useResource(() => penalties.list(), []);

  async function act(kind: string, api: any, resource: any, id: any, decision: "approve" | "reject") {
    setMessage("");
    setFailure("");
    setBusyKey(`${kind}-${id}-${decision}`);
    try {
      await api[decision](id);
      setMessage(`${kind} #${id} ${decision === "approve" ? "approved" : "rejected"}.`);
      resource.reload();
    } catch (error) {
      setFailure(errorMessage(error));
    } finally {
      setBusyKey("");
    }
  }

  function decisionColumn(kind: string, api: any, resource: any) {
    return {
      key: "decision",
      label: "Decision",
      render: (row: any) => (
        <div className="flex gap-2">
          <Button
            variant="primary"
            disabled={busyKey.startsWith(`${kind}-${row.id}-`)}
            onClick={() => act(kind, api, resource, row.id, "approve")}
          >
            Approve
          </Button>
          <Button
            variant="outline"
            disabled={busyKey.startsWith(`${kind}-${row.id}-`)}
            onClick={() => act(kind, api, resource, row.id, "reject")}
          >
            Reject
          </Button>
        </div>
      ),
    };
  }

  const loanRows = (loanQueue.data || []).filter(isPending);
  const expenseRows = (expenseQueue.data || []).filter(isPending);
  const payrollRows = (payrollQueue.data || []).filter(isPending);
  const penaltyRows = (penaltyQueue.data || []).filter(isPending);
  const total = loanRows.length + expenseRows.length + payrollRows.length + penaltyRows.length;

  return (
    <>
      <PageHeader
        title="Approvals"
        description={`${total} items waiting for a decision. Maker-checker applies: you cannot approve what you created.`}
      />
      <Notice tone="success">{message}</Notice>
      <Notice tone="danger">{failure}</Notice>
      <Notice tone="danger">
        {loanQueue.error || expenseQueue.error || payrollQueue.error || penaltyQueue.error}
      </Notice>

      <div className="space-y-4">
        <Card title="Loans" description={`${loanRows.length} pending`}>
          <DataTable
            rows={loanRows}
            empty={loanQueue.loading ? "Loading…" : "No loans waiting for approval."}
            columns={[
              { key: "id", label: "Loan" },
              {
                key: "borrower_name",
                label: "Borrower",
                render: (r: any) => r.borrower_name || r.borrower?.name || "—",
              },
              { key: "principal_amount", label: "Principal", render: (r: any) => money(r.principal_amount) },
              { key: "term_months", label: "Term" },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
              decisionColumn("Loan", loans, loanQueue),
            ]}
          />
        </Card>

        <Card title="Expenses" description={`${expenseRows.length} pending`}>
          <DataTable
            rows={expenseRows}
            empty={expenseQueue.loading ? "Loading…" : "No expenses waiting for approval."}
            columns={[
              { key: "id", label: "Ref" },
              { key: "description", label: "Description" },
              { key: "category", label: "Category" },
              { key: "amount", label: "Amount", render: (r: any) => money(r.amount) },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
              decisionColumn("Expense", expenses, expenseQueue),
            ]}
          />
        </Card>

        <Card title="Payroll" description={`${payrollRows.length} pending`}>
          <DataTable
            rows={payrollRows}
            empty={payrollQueue.loading ? "Loading…" : "No payroll batches waiting for approval."}
            columns={[
              { key: "id", label: "Batch" },
              { key: "period", label: "Period", render: (r: any) => r.period || r.month || "—" },
              { key: "total_amount", label: "Total", render: (r: any) => money(r.total_amount) },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
              decisionColumn("Payroll", payroll, payrollQueue),
            ]}
          />
        </Card>

        <Card title="Penalties" description={`${penaltyRows.length} pending`}>
          <DataTable
            rows={penaltyRows}
            empty={penaltyQueue.loading ? "Loading…" : "No penalties waiting for approval."}
            columns={[
              { key: "id", label: "Ref" },
              { key: "loan_id", label: "Loan" },
              {
                key: "borrower_name",
                label: "Borrower",
                render: (r: any) => r.borrower_name || r.borrower?.name || "—",
              },
              { key: "amount", label: "Amount", render: (r: any) => money(r.amount) },
              { key: "reason", label: "Reason" },
              decisionColumn("Penalty", penalties, penaltyQueue),
            ]}
          />
        </Card>
      </div>
    </>
  );
}
