import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, InlineNote, MoneyInput, PageHeader, Select, StatusBadge, money, fmtNumber } from "../components/lms-ui";
import useAutoRefresh from "../hooks/useAutoRefresh.js";
import useResource from "../hooks/useResource.js";
import { errorMessage, getUser, hasPermission, loans, penalties } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/penalties")({
  head: () => ({
    meta: [
      { title: "Penalties — Microfinance LMS" },
      { name: "description", content: "Submit and review loan penalties." },
    ],
  }),
  component: () => (
    <AppShell>
      <PenaltiesPage />
    </AppShell>
  ),
});

const PENDING = /pending/i;
const EMPTY = { loan_id: "", amount: "", reason: "" };

function PenaltiesPage() {
  const user = getUser();
  const canCreate = hasPermission(user, "penalties:create");
  const canApprove = hasPermission(user, "penalties:approve");

  const [filters, setFilters] = useState({ status: "", loan_id: "" });
  const list = useResource(() => penalties.list(filters), [filters.status, filters.loan_id]);
  const loanList = useResource(() => loans.list(), []);
  const activeLoans = (loanList.data || []).filter((l: any) => l.status === "active");
  const [form, setForm] = useState<any>(EMPTY);
  const [busyKey, setBusyKey] = useState("");

  useAutoRefresh(list.reload);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!form.loan_id) { showToast("Select the loan this penalty applies to.", "danger"); return; }
    if (!Number(form.amount)) { showToast("Enter the penalty amount.", "danger"); return; }
    if (!form.reason.trim()) { showToast("Enter the reason for the penalty.", "danger"); return; }
    try {
      await penalties.create({ loan_id: Number(form.loan_id), amount: Number(form.amount), reason: form.reason.trim() });
      setForm(EMPTY);
      showToast("Penalty submitted for approval.", "success");
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  const label = (row: any) => `Loan #${row.loan_id}${row.borrower_name ? ` — ${row.borrower_name}` : ""}`;
  // The whole identifier is the link (Part 5.2), not just the "#" character.
  const loanLink = (row: any) => (
    <Link to="/loans/$id" params={{ id: String(row.loan_id) }} className="text-primary underline">
      {label(row)}
    </Link>
  );

  async function decide(row: any, action: "approve" | "reject") {
    const question =
      action === "approve"
        ? `This will add ${money(row.amount)} to ${label(row)}'s outstanding balance. Approve?`
        : `This will reject the ${money(row.amount)} penalty on ${label(row)}. Are you sure?`;
    if (!window.confirm(question)) return;
    let rejection_reason: string | undefined;
    if (action === "reject") {
      rejection_reason = window.prompt("Reason for rejection:") || undefined;
      if (!rejection_reason) return;
    }
    setBusyKey(`${row.id}-${action}`);
    try {
      await penalties[action](row.id, action === "reject" ? { rejection_reason } : undefined);
      showToast(`Penalty ${action === "approve" ? "approved" : "rejected"}.`, "success");
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusyKey("");
    }
  }

  async function reverse(row: any) {
    const reason = window.prompt(
      `This will remove ${money(row.amount)} from ${label(row)}'s outstanding balance. Enter a reason to reverse this penalty:`,
    );
    if (!reason) return;
    setBusyKey(`${row.id}-reverse`);
    try {
      await penalties.reverse(row.id, reason);
      showToast(`Penalty reversed on ${label(row)}.`, "success");
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusyKey("");
    }
  }

  const rows = list.data || [];
  const pendingRows = rows.filter((r: any) => PENDING.test(r.status) && r.can_decide);

  return (
    <>
      <PageHeader title="Penalties" description="Submit and review loan penalties." />
      <InlineNote tone="danger">{list.error}</InlineNote>

      {canApprove ? (
        <Card title="Pending my approval" description={`${fmtNumber(pendingRows.length)} penalties`} className="mb-4">
          <DataTable
            rows={pendingRows}
            empty="No penalties waiting for your approval."
            columns={[
              { key: "loan", label: "Loan", render: (r: any) => loanLink(r) },
              { key: "amount", label: "Amount", render: (r: any) => money(r.amount) },
              { key: "reason", label: "Reason" },
              { key: "created_by_name", label: "Added by" },
              {
                key: "actions",
                label: "",
                render: (r: any) => (
                  <div className="flex gap-2">
                    <Button disabled={busyKey === `${r.id}-approve`} onClick={() => decide(r, "approve")}>
                      Approve
                    </Button>
                    <Button variant="outline" disabled={busyKey === `${r.id}-reject`} onClick={() => decide(r, "reject")}>
                      Reject
                    </Button>
                  </div>
                ),
              },
            ]}
          />
        </Card>
      ) : null}

      <div className={`grid gap-4 ${canCreate ? "xl:grid-cols-[1.7fr_1fr]" : ""}`}>
        <Card title="Penalty register">
          <div className="mb-4 grid gap-2 sm:grid-cols-2">
            <Select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
              <option value="">All statuses</option>
              <option value="pending">Waiting for approval</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="reversed">Reversed</option>
            </Select>
            <Select value={filters.loan_id} onChange={(e) => setFilters({ ...filters, loan_id: e.target.value })}>
              <option value="">All loans</option>
              {(loanList.data || []).map((l: any) => (
                <option key={l.id} value={l.id}>
                  Loan #{l.id} — {l.borrower_name}
                </option>
              ))}
            </Select>
          </div>
          <DataTable
            rows={rows}
            empty={list.loading ? "Loading..." : "No penalties."}
            columns={[
              { key: "loan", label: "Loan", render: (r: any) => loanLink(r) },
              { key: "amount", label: "Amount", render: (r: any) => money(r.amount) },
              { key: "reason", label: "Reason" },
              { key: "created_by_name", label: "Added by" },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} reason={r.rejection_reason} /> },
              {
                key: "actions",
                label: "",
                render: (r: any) =>
                  r.can_reverse ? (
                    <Button variant="outline" disabled={busyKey === `${r.id}-reverse`} onClick={() => reverse(r)}>
                      Reverse
                    </Button>
                  ) : null,
              },
            ]}
            mobileCard={(r: any) => (
              <div>
                <div className="flex items-start justify-between gap-3">
                  <p className="min-w-0 truncate font-medium">{label(r)}</p>
                  <p className="shrink-0 font-semibold tabular-nums">{money(r.amount)}</p>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{r.reason}</p>
                <div className="mt-2 flex items-center justify-between gap-3">
                  <StatusBadge status={r.status} reason={r.rejection_reason} />
                  {r.can_reverse ? (
                    <Button variant="outline" compact disabled={busyKey === `${r.id}-reverse`} onClick={() => reverse(r)}>
                      Reverse
                    </Button>
                  ) : null}
                </div>
              </div>
            )}
          />
        </Card>
        {canCreate ? (
          <Card title="Add penalty">
            <form className="space-y-3" onSubmit={create} noValidate>
              <Field label="Loan" hint="Penalties can only be added to active loans.">
                <Select value={form.loan_id} onChange={(e) => setForm({ ...form, loan_id: e.target.value })}>
                  <option value="">Select loan</option>
                  {activeLoans.map((l: any) => (
                    <option key={l.id} value={l.id}>
                      Loan #{l.id} — {l.borrower_name} (balance {money(l.outstanding_balance)})
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Amount">
                <MoneyInput value={form.amount} onValueChange={(v) => setForm({ ...form, amount: v })} />
              </Field>
              <Field label="Reason">
                <Input required value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
              </Field>
              <Button type="submit" className="w-full">
                Submit penalty
              </Button>
            </form>
          </Card>
        ) : null}
      </div>
    </>
  );
}
