import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import {
  Button,
  Card,
  DataTable,
  Field,
  Input,
  Notice,
  PageHeader,
  Select,
  money,
} from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { errorMessage, loans, repayments } from "../lib/api";

export const Route = createFileRoute("/repayments")({
  head: () => ({
    meta: [
      { title: "Repayments — Microfinance LMS" },
      { name: "description", content: "Record loan repayments and review the payment history with running balances." },
      { property: "og:title", content: "Repayments — Microfinance LMS" },
      { property: "og:description", content: "Record repayments and track balances after each payment." },
    ],
  }),
  component: () => (
    <AppShell>
      <RepaymentsPage />
    </AppShell>
  ),
});

const EMPTY = { loan_id: "", amount_paid: "", payment_date: "" };

function RepaymentsPage() {
  const list = useResource(() => repayments.list(), []);
  const loanList = useResource(() => loans.list(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);

  const selectedLoan: any = (loanList.data || []).find((l: any) => String(l.id) === String(form.loan_id));

  function validate() {
    const next: Record<string, string> = {};
    if (!form.loan_id) next.loan_id = "Select the loan being paid.";
    if (!Number(form.amount_paid) || Number(form.amount_paid) <= 0) next.amount_paid = "Enter the amount paid.";
    if (!form.payment_date) next.payment_date = "Select the payment date.";
    if (
      selectedLoan?.outstanding_balance !== undefined &&
      Number(form.amount_paid) > Number(selectedLoan.outstanding_balance) + 0.001
    ) {
      next.amount_paid = `Amount is higher than the outstanding balance (${money(selectedLoan.outstanding_balance)}).`;
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setMessage("");
    setFailure("");
    if (!validate()) return;
    setBusy(true);
    try {
      await repayments.create({
        loan_id: form.loan_id,
        amount_paid: Number(form.amount_paid),
        payment_date: form.payment_date,
      });
      setForm(EMPTY);
      setMessage("Repayment recorded. The loan balance has been updated.");
      list.reload();
      loanList.reload();
    } catch (error) {
      setFailure(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Repayments" description="Record payments against active loans." />
      <Notice tone="danger">{list.error}</Notice>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card title="Repayment history" description={`${(list.data || []).length} records`}>
          <DataTable
            rows={list.data || []}
            empty={list.loading ? "Loading…" : "No repayments recorded yet."}
            columns={[
              { key: "id", label: "Receipt" },
              { key: "loan_id", label: "Loan" },
              {
                key: "borrower_name",
                label: "Borrower",
                render: (r: any) => r.borrower_name || r.borrower?.name || "—",
              },
              { key: "amount_paid", label: "Amount paid", render: (r: any) => money(r.amount_paid) },
              { key: "payment_date", label: "Payment date" },
              {
                key: "balance_after",
                label: "Balance after",
                render: (r: any) => money(r.balance_after ?? r.outstanding_balance),
              },
            ]}
          />
        </Card>

        <Card title="Record repayment">
          <form onSubmit={onSubmit} className="space-y-3" noValidate>
            <Notice tone="success">{message}</Notice>
            <Notice tone="danger">{failure}</Notice>
            <Field label="Loan" error={errors.loan_id}>
              <Select value={form.loan_id} onChange={(e: any) => setForm({ ...form, loan_id: e.target.value })}>
                <option value="">Select loan</option>
                {(loanList.data || []).map((l: any) => (
                  <option key={l.id} value={l.id}>
                    #{l.id} — {l.borrower_name || l.borrower?.name || "borrower"}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label="Amount paid"
              error={errors.amount_paid}
              hint={selectedLoan ? `Outstanding balance: ${money(selectedLoan.outstanding_balance)}` : undefined}
            >
              <Input
                type="number"
                step="0.01"
                value={form.amount_paid}
                onChange={(e: any) => setForm({ ...form, amount_paid: e.target.value })}
              />
            </Field>
            <Field label="Payment date" error={errors.payment_date}>
              <Input
                type="date"
                value={form.payment_date}
                onChange={(e: any) => setForm({ ...form, payment_date: e.target.value })}
              />
            </Field>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Saving…" : "Record repayment"}
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}
