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
  StatusBadge,
  money,
} from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { borrowers, errorMessage, loanProducts, loans } from "../lib/api";

export const Route = createFileRoute("/loans")({
  head: () => ({
    meta: [
      { title: "Loans — Microfinance LMS" },
      { name: "description", content: "Create loans, track principal, interest, term and status from draft to closed." },
      { property: "og:title", content: "Loans — Microfinance LMS" },
      { property: "og:description", content: "Loan book with creation form and status tracking." },
    ],
  }),
  component: () => (
    <AppShell>
      <LoansPage />
    </AppShell>
  ),
});

const EMPTY = {
  borrower_id: "",
  loan_product_id: "",
  principal_amount: "",
  interest_rate: "",
  term_months: "",
  start_date: "",
};

function LoansPage() {
  const list = useResource(() => loans.list(), []);
  const borrowerList = useResource(() => borrowers.list(), []);
  const productList = useResource(() => loanProducts.list(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);

  function set(key: string, value: string) {
    const next = { ...form, [key]: value };
    if (key === "loan_product_id") {
      const product: any = (productList.data || []).find((p: any) => String(p.id) === value);
      if (product && !form.interest_rate) next.interest_rate = String(product.default_interest_rate ?? "");
    }
    setForm(next);
  }

  function validate() {
    const next: Record<string, string> = {};
    if (!form.borrower_id) next.borrower_id = "Select a borrower.";
    if (!form.loan_product_id) next.loan_product_id = "Select a loan product.";
    if (!Number(form.principal_amount)) next.principal_amount = "Enter the principal amount.";
    if (form.interest_rate === "" || Number(form.interest_rate) < 0) next.interest_rate = "Enter an interest rate.";
    if (!Number(form.term_months)) next.term_months = "Enter the term in months.";
    if (!form.start_date) next.start_date = "Select a start date.";

    const product: any = (productList.data || []).find((p: any) => String(p.id) === String(form.loan_product_id));
    if (product) {
      const amount = Number(form.principal_amount);
      const term = Number(form.term_months);
      if (product.min_amount && amount < Number(product.min_amount))
        next.principal_amount = `Minimum for this product is ${money(product.min_amount)}.`;
      if (product.max_amount && amount > Number(product.max_amount))
        next.principal_amount = `Maximum for this product is ${money(product.max_amount)}.`;
      if (product.min_term_months && term < Number(product.min_term_months))
        next.term_months = `Minimum term is ${product.min_term_months} months.`;
      if (product.max_term_months && term > Number(product.max_term_months))
        next.term_months = `Maximum term is ${product.max_term_months} months.`;
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
      await loans.create({
        borrower_id: form.borrower_id,
        loan_product_id: form.loan_product_id,
        principal_amount: Number(form.principal_amount),
        interest_rate: Number(form.interest_rate),
        term_months: Number(form.term_months),
        start_date: form.start_date,
      });
      setForm(EMPTY);
      setMessage("Loan created and sent for approval.");
      list.reload();
    } catch (error) {
      setFailure(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Loans" description="Loan book and new loan applications." />
      <Notice tone="danger">{list.error}</Notice>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card title="Loan list" description={`${(list.data || []).length} records`}>
          <DataTable
            rows={list.data || []}
            empty={list.loading ? "Loading…" : "No loans yet."}
            columns={[
              { key: "id", label: "Loan" },
              { key: "borrower_name", label: "Borrower", render: (r: any) => r.borrower_name || r.borrower?.name || "—" },
              { key: "product_name", label: "Product", render: (r: any) => r.product_name || r.loan_product?.name || "—" },
              { key: "principal_amount", label: "Principal", render: (r: any) => money(r.principal_amount) },
              { key: "interest_rate", label: "Rate %", render: (r: any) => r.interest_rate ?? "—" },
              { key: "term_months", label: "Term" },
              { key: "start_date", label: "Start" },
              { key: "outstanding_balance", label: "Balance", render: (r: any) => money(r.outstanding_balance) },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
            ]}
          />
        </Card>

        <Card title="Create loan">
          <form onSubmit={onSubmit} className="space-y-3" noValidate>
            <Notice tone="success">{message}</Notice>
            <Notice tone="danger">{failure}</Notice>
            <Field label="Borrower" error={errors.borrower_id}>
              <Select value={form.borrower_id} onChange={(e: any) => set("borrower_id", e.target.value)}>
                <option value="">Select borrower</option>
                {(borrowerList.data || []).map((b: any) => (
                  <option key={b.id} value={b.id}>
                    {b.name} — {b.phone}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Loan product" error={errors.loan_product_id}>
              <Select value={form.loan_product_id} onChange={(e: any) => set("loan_product_id", e.target.value)}>
                <option value="">Select product</option>
                {(productList.data || []).map((p: any) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Principal amount" error={errors.principal_amount}>
              <Input type="number" value={form.principal_amount} onChange={(e: any) => set("principal_amount", e.target.value)} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Interest rate (%)" error={errors.interest_rate}>
                <Input type="number" step="0.01" value={form.interest_rate} onChange={(e: any) => set("interest_rate", e.target.value)} />
              </Field>
              <Field label="Term (months)" error={errors.term_months}>
                <Input type="number" value={form.term_months} onChange={(e: any) => set("term_months", e.target.value)} />
              </Field>
            </div>
            <Field label="Start date" error={errors.start_date}>
              <Input type="date" value={form.start_date} onChange={(e: any) => set("start_date", e.target.value)} />
            </Field>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Saving…" : "Create loan"}
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}
