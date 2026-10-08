import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, InlineNote, PageHeader, StatusBadge, fmtNumber, money, percent } from "../components/lms-ui";
import { LeaveDecisionModal } from "../components/LeaveDecisionModal";
import useAutoRefresh from "../hooks/useAutoRefresh.js";
import useResource from "../hooks/useResource.js";
import { errorMessage, getUser, hasPermission, leaveRequests, loans, penalties } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/approvals")({
  head: () => ({
    meta: [
      { title: "Approvals — Microfinance LMS" },
      { name: "description", content: "Decide pending loans, penalties and leave requests." },
      { property: "og:title", content: "Approvals — Microfinance LMS" },
      { property: "og:description", content: "Aggregated approval queue: loans, penalties and leave." },
    ],
  }),
  component: () => (
    <AppShell>
      <ApprovalsPage />
    </AppShell>
  ),
});

const PENDING = /pending|submitted|awaiting|review/i;
// Same rule the module pages use: pending AND the backend says this user may decide it.
const decidable = (row: any) => PENDING.test(String(row.status || "")) && row.can_decide;

// Expenses, payroll and employees are no longer maker-checker (Part 1.1) —
// they are recorded/finalized directly on their own pages, not here. Only
// loans, penalties and leave requests still go through a decision.
function ApprovalsPage() {
  const user = getUser();
  const [busyKey, setBusyKey] = useState("");
  const [reviewingLeave, setReviewingLeave] = useState<any>(null);

  const loanQueue = useResource(() => loans.list(), []);
  const penaltyQueue = useResource(() => penalties.list(), []);
  const leaveQueue = useResource(() => leaveRequests.list(), []);

  useAutoRefresh(() => {
    loanQueue.reload();
    penaltyQueue.reload();
    leaveQueue.reload();
  });

  async function act(kind: string, key: string, api: any, resource: any, row: any, decision: "approve" | "reject", consequence: string) {
    const question = decision === "approve" ? `${consequence} Approve?` : `${consequence.replace(/^This will approve/, "This will reject")} Are you sure?`;
    if (!window.confirm(question)) return;
    let rejection_reason: string | undefined;
    if (decision === "reject") {
      rejection_reason = window.prompt("Reason for rejection:") || undefined;
      if (!rejection_reason) return;
    }
    setBusyKey(`${key}-${row.id}`);
    try {
      // leave requests take the reason as a bare argument, everything else as { rejection_reason }
      if (kind === "Leave request") await api[decision](row.id, decision === "reject" ? rejection_reason : undefined);
      else await api[decision](row.id, decision === "reject" ? { rejection_reason } : undefined);
      showToast(`${kind} ${decision === "approve" ? "approved" : "rejected"}.`, "success");
      resource.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusyKey("");
    }
  }

  function decisionColumn(kind: string, key: string, api: any, resource: any, describe: (row: any) => string) {
    return {
      key: "decision",
      label: "Decision",
      render: (row: any) => (
        <div className="flex gap-2">
          <Button disabled={busyKey === `${key}-${row.id}`} onClick={() => act(kind, key, api, resource, row, "approve", describe(row))}>
            Approve
          </Button>
          <Button variant="outline" disabled={busyKey === `${key}-${row.id}`} onClick={() => act(kind, key, api, resource, row, "reject", describe(row))}>
            Reject
          </Button>
        </div>
      ),
    };
  }

  const loanRows = (loanQueue.data || []).filter(decidable);
  const penaltyRows = (penaltyQueue.data || []).filter(decidable);
  const leaveRows = (leaveQueue.data || []).filter(decidable);
  const total = loanRows.length + penaltyRows.length + leaveRows.length;

  return (
    <>
      <PageHeader
        title="Approvals"
        description={`${fmtNumber(total)} item${total === 1 ? "" : "s"} waiting for your decision.`}
      />
      <InlineNote tone="danger">{loanQueue.error || penaltyQueue.error || leaveQueue.error}</InlineNote>

      <div className="space-y-4">
        {hasPermission(user, "loans:approve") ? (
          <Card title="Loans" description={`${fmtNumber(loanRows.length)} pending`}>
            <DataTable
              rows={loanRows}
              empty={loanQueue.loading ? "Loading…" : "No loans waiting for approval."}
              columns={[
                {
                  key: "loan",
                  label: "Loan",
                  render: (r: any) => (
                    <Link to="/loans/$id" params={{ id: String(r.id) }} className="text-primary underline">
                      #{r.id}
                    </Link>
                  ),
                },
                { key: "borrower_name", label: "Borrower" },
                { key: "principal_amount", label: "Principal", render: (r: any) => money(r.principal_amount) },
                { key: "interest_rate", label: "Monthly Rate (%)", render: (r: any) => percent(r.interest_rate) },
                { key: "term_months", label: "Term (months)", render: (r: any) => fmtNumber(r.term_months) },
                { key: "creator_name_snapshot", label: "Created by" },
                decisionColumn("Loan", "loan", loans, loanQueue, (r) =>
                  `This will approve Loan #${r.id} for ${r.borrower_name}: ${money(r.principal_amount)} at ${percent(r.interest_rate)} per month over ${fmtNumber(r.term_months)} months, and send the schedule to the borrower.`),
              ]}
            />
          </Card>
        ) : null}

        {hasPermission(user, "penalties:approve") ? (
          <Card title="Penalties" description={`${fmtNumber(penaltyRows.length)} pending`}>
            <DataTable
              rows={penaltyRows}
              empty={penaltyQueue.loading ? "Loading…" : "No penalties waiting for approval."}
              columns={[
                {
                  key: "loan",
                  label: "Loan",
                  render: (r: any) => (
                    <Link to="/loans/$id" params={{ id: String(r.loan_id) }} className="text-primary underline">
                      #{r.loan_id} — {r.borrower_name}
                    </Link>
                  ),
                },
                { key: "amount", label: "Amount", render: (r: any) => money(r.amount) },
                { key: "reason", label: "Reason" },
                { key: "created_by_name", label: "Added by" },
                decisionColumn("Penalty", "penalty", penalties, penaltyQueue, (r) =>
                  `This will approve a ${money(r.amount)} penalty, adding it to Loan #${r.loan_id} (${r.borrower_name})'s outstanding balance.`),
              ]}
            />
          </Card>
        ) : null}

        {hasPermission(user, "leave:manage") ? (
          <Card title="Leave requests" description={`${fmtNumber(leaveRows.length)} pending`}>
            <DataTable
              rows={leaveRows}
              empty={leaveQueue.loading ? "Loading…" : "No leave requests waiting for approval."}
              columns={[
                { key: "employee_name", label: "Employee" },
                { key: "leave_type", label: "Type" },
                { key: "start_date", label: "From" },
                { key: "end_date", label: "To" },
                { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
                {
                  key: "decision",
                  label: "Decision",
                  render: (r: any) => <Button onClick={() => setReviewingLeave(r)}>Review</Button>,
                },
              ]}
            />
          </Card>
        ) : null}
      </div>

      {reviewingLeave ? (
        <LeaveDecisionModal leave={reviewingLeave} onClose={() => setReviewingLeave(null)} onDecided={leaveQueue.reload} />
      ) : null}
    </>
  );
}
