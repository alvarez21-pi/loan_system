import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, MoneyInput, NumberInput, PageHeader, fmtNumber, money } from "../components/lms-ui";
import { calculator, errorMessage } from "../lib/api";
import { localDateString as today } from "../lib/utils";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/loan-calculator")({
  head: () => ({
    meta: [
      { title: "Loan Calculator — Microfinance LMS" },
      { name: "description", content: "Quote a reducing-balance schedule for a prospective borrower." },
    ],
  }),
  component: () => (
    <AppShell>
      <CalculatorPage />
    </AppShell>
  ),
});

function CalculatorPage() {
  const [form, setForm] = useState({ principal: "", interest_rate: "", term_months: "", start_date: today() });
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!Number(form.principal) || form.interest_rate === "" || !Number(form.term_months)) {
      showToast("Enter the principal, the monthly interest rate and the term in months.", "danger");
      return;
    }
    setBusy(true);
    try {
      setResult(
        await calculator.preview({
          principal: Number(form.principal),
          interest_rate: Number(form.interest_rate),
          term_months: Number(form.term_months),
          interest_type: "reducing_balance",
          start_date: form.start_date || undefined,
        }),
      );
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Loan calculator" description="Preview a repayment schedule without saving." />
      <div className="grid gap-4 xl:grid-cols-[1fr_1.8fr]">
        <Card title="Preview inputs">
          <form className="space-y-3" onSubmit={submit} noValidate>
            <Field label="Principal">
              <MoneyInput value={form.principal} onValueChange={(v) => setForm({ ...form, principal: v })} />
            </Field>
            <Field label="Monthly Interest Rate (%)">
              <NumberInput decimals={2} value={form.interest_rate} onValueChange={(v) => setForm({ ...form, interest_rate: v })} />
            </Field>
            <Field label="Term (months)">
              <NumberInput integer value={form.term_months} onValueChange={(v) => setForm({ ...form, term_months: v })} />
            </Field>
            <Field label="Start date">
              <Input type="date" value={form.start_date} onChange={(e: any) => setForm({ ...form, start_date: e.target.value })} />
            </Field>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Calculating..." : "Calculate schedule"}
            </Button>
          </form>
        </Card>
        <Card title="Amortization schedule">
          <DataTable
            rows={result?.schedule || []}
            empty={result ? "No schedule" : "Enter values to preview a schedule."}
            columns={[
              { key: "period", label: "Period", render: (r: any) => fmtNumber(r.period) },
              { key: "due_date", label: "Due date" },
              { key: "principal_portion", label: "Principal", render: (r: any) => money(r.principal_portion) },
              { key: "interest_portion", label: "Interest", render: (r: any) => money(r.interest_portion) },
              { key: "payment_amount", label: "Payment", render: (r: any) => money(r.payment_amount) },
              { key: "balance_after", label: "Balance", render: (r: any) => money(r.balance_after) },
            ]}
            totalsRow={
              result?.totals
                ? ["Totals", "", money(result.totals.total_principal), money(result.totals.total_interest), money(result.totals.total_payable), ""]
                : undefined
            }
          />
        </Card>
      </div>
    </>
  );
}
