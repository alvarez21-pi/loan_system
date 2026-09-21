import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, Notice, PageHeader, money } from "../components/lms-ui";
import { calculator, errorMessage } from "../lib/api";

export const Route = createFileRoute("/loan-calculator")({ component: CalculatorPage });

function CalculatorPage() {
  const [form, setForm] = useState({ principal: "", interest_rate: "", term_months: "" });
  const [result, setResult] = useState<any>(null);
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setFailure(""); setBusy(true);
    try { setResult(await calculator.preview({ ...form, interest_type: "reducing_balance" })); }
    catch (error) { setFailure(errorMessage(error)); } finally { setBusy(false); }
  }
  return <AppShell><PageHeader title="Loan calculator" description="Preview a reducing-balance schedule without creating a loan." />
    <div className="grid gap-4 xl:grid-cols-[1fr_1.8fr]">
      <Card title="Preview inputs"><form className="space-y-3" onSubmit={submit}>
        <Field label="Principal"><Input type="number" step="0.01" required value={form.principal} onChange={(e) => setForm({ ...form, principal: e.target.value })} /></Field>
        <Field label="Annual interest rate (%)"><Input type="number" step="0.01" required value={form.interest_rate} onChange={(e) => setForm({ ...form, interest_rate: e.target.value })} /></Field>
        <Field label="Term (months)"><Input type="number" min="1" required value={form.term_months} onChange={(e) => setForm({ ...form, term_months: e.target.value })} /></Field>
        <Notice tone="danger">{failure}</Notice><Button type="submit" disabled={busy} className="w-full">{busy ? "Calculating..." : "Calculate schedule"}</Button>
      </form></Card>
      <Card title="Amortization schedule"><DataTable rows={result?.schedule || []} empty={result ? "No schedule" : "Enter values to preview a schedule."} columns={[
        { key: "period", label: "Period" }, { key: "principal_portion", label: "Principal", render: (r: any) => money(r.principal_portion) }, { key: "interest_portion", label: "Interest", render: (r: any) => money(r.interest_portion) }, { key: "payment_amount", label: "Payment", render: (r: any) => money(r.payment_amount) }, { key: "balance_after", label: "Balance", render: (r: any) => money(r.balance_after) },
      ]} />{result?.totals ? <div className="mt-4 grid gap-2 border-t border-border pt-4 sm:grid-cols-3"><div>Total principal: {money(result.totals.total_principal)}</div><div>Total interest: {money(result.totals.total_interest)}</div><div>Total paid: {money(result.totals.total_paid)}</div></div> : null}</Card>
    </div></AppShell>;
}
