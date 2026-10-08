import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { RepaymentForm } from "../components/RepaymentForm";
import { Card, DataTable, Field, ListStatus, PageHeader, Pagination, Select, SearchInput, money } from "../components/lms-ui";
import usePaginatedResource from "../hooks/usePaginatedResource.js";
import useResource from "../hooks/useResource.js";
import { getUser, hasPermission, loans, repayments } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/repayments")({
  head: () => ({
    meta: [
      { title: "Repayments — Microfinance LMS" },
      { name: "description", content: "Repayment history with running balances across every loan." },
      { property: "og:title", content: "Repayments — Microfinance LMS" },
      { property: "og:description", content: "Repayment history and balances after each payment." },
    ],
  }),
  component: () => (
    <AppShell>
      <RepaymentsPage />
    </AppShell>
  ),
});

function RepaymentsPage() {
  const user = getUser();
  const navigate = useNavigate();
  const canRecord = hasPermission(user, "repayments:record");
  const list = usePaginatedResource((params: any) => repayments.list(params) as Promise<{ data: any[]; pagination: any }>, []);
  // Only a loan that can actually take a payment right now (Part 5.1: the
  // Repayments page picks the loan FIRST, then the identical form/logic the
  // loan detail page uses runs either way).
  const loanList = useResource(() => (canRecord ? loans.list() : Promise.resolve({ data: [] })), []);
  const activeLoans = (loanList.data || []).filter((l: any) => l.status === "active");
  const [loanId, setLoanId] = useState("");
  const selectedLoan = activeLoans.find((l: any) => String(l.id) === loanId);

  function onRecorded(result: any) {
    const after = result?.loan;
    showToast(
      after?.status === "closed"
        ? "Repayment recorded. This loan is now fully paid."
        : `Repayment recorded. The remaining schedule was recalculated on the new balance of ${money(after?.outstanding_balance)}.`,
      "success",
    );
    setLoanId("");
    list.reload();
    loanList.reload();
  }

  return (
    <>
      <PageHeader
        title="Repayments"
        description="Payment history across every loan."
      />

      <div className={`grid gap-4 ${canRecord ? "xl:grid-cols-[1.6fr_1fr]" : ""}`}>
        <Card
          title="Repayment history"
          description={`${list.pagination ? list.pagination.total : (list.data || []).length} records`}
          actions={<SearchInput value={list.q} onChange={list.setQ} placeholder="Search by borrower name" />}
        >
          <ListStatus loading={list.loading} error={list.error} empty={!list.loading && !list.error && (list.data || []).length === 0} emptyMessage="No repayments recorded yet." />
          {!list.loading && !list.error && (list.data || []).length > 0 ? (
            <DataTable
              rows={list.data || []}
              onRowClick={(r: any) => navigate({ to: "/loans/$id", params: { id: String(r.loan_id) } })}
              sort={list.sort}
              order={list.order}
              onSort={list.toggleSort}
              columns={[
                { key: "id", label: "Receipt" },
                {
                  key: "loan_id",
                  label: "Loan",
                  render: (r: any) => (
                    <Link to="/loans/$id" params={{ id: String(r.loan_id) }} className="text-primary underline" onClick={(e) => e.stopPropagation()}>
                      Loan #{r.loan_id}
                    </Link>
                  ),
                },
                {
                  key: "borrower_name",
                  label: "Borrower",
                  sortKey: "borrower_name",
                  render: (r: any) => r.borrower_name || "—",
                },
                { key: "amount_paid", label: "Amount paid", render: (r: any) => money(r.amount_paid) },
                { key: "payment_date", label: "Payment date", sortKey: "payment_date" },
                {
                  key: "balance_after",
                  label: "Balance after",
                  render: (r: any) => money(r.balance_after ?? r.outstanding_balance),
                },
              ]}
            />
          ) : null}
          <Pagination page={list.page} pagination={list.pagination} onPageChange={list.setPage} />
        </Card>

        {canRecord ? (
          <Card title="Record a repayment">
            <div className="space-y-3">
              <Field label="Loan">
                <Select value={loanId} onChange={(e) => setLoanId(e.target.value)}>
                  <option value="">Select loan</option>
                  {activeLoans.map((l: any) => (
                    <option key={l.id} value={l.id}>
                      Loan #{l.id} — {l.borrower_name} (balance {money(l.outstanding_balance)})
                    </option>
                  ))}
                </Select>
              </Field>
              {activeLoans.length === 0 ? (
                <p className="text-sm text-muted-foreground">No active loans to record a repayment against right now.</p>
              ) : null}
              {selectedLoan ? <RepaymentForm loan={selectedLoan} onRecorded={onRecorded} /> : null}
            </div>
          </Card>
        ) : null}
      </div>
    </>
  );
}
