import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, Notice, PageHeader, money } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { errorMessage, loanProducts } from "../lib/api";

export const Route = createFileRoute("/loan-products")({
  head: () => ({
    meta: [
      { title: "Loan Products — Microfinance LMS" },
      { name: "description", content: "Define loan products with interest rates, term limits and amount ranges." },
      { property: "og:title", content: "Loan Products — Microfinance LMS" },
      { property: "og:description", content: "Loan product catalogue with rates, terms and amount limits." },
    ],
  }),
  component: () => (
    <AppShell>
      <LoanProductsPage />
    </AppShell>
  ),
});

const EMPTY = {
  name: "",
  default_interest_rate: "",
  min_term_months: "",
  max_term_months: "",
  min_amount: "",
  max_amount: "",
};

function LoanProductsPage() {
  const list = useResource(() => loanProducts.list(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);

  function set(key: string, value: string) {
    setForm({ ...form, [key]: value });
  }

  function validate() {
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "Product name is required.";
    const rate = Number(form.default_interest_rate);
    if (form.default_interest_rate === "" || Number.isNaN(rate) || rate < 0) next.default_interest_rate = "Enter a valid rate (%).";
    const minT = Number(form.min_term_months);
    const maxT = Number(form.max_term_months);
    if (!minT || minT < 1) next.min_term_months = "Minimum term must be at least 1 month.";
    if (!maxT || maxT < minT) next.max_term_months = "Maximum term must be greater than the minimum.";
    const minA = Number(form.min_amount);
    const maxA = Number(form.max_amount);
    if (!minA || minA <= 0) next.min_amount = "Enter a minimum amount.";
    if (!maxA || maxA < minA) next.max_amount = "Maximum amount must be greater than the minimum.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  function startEdit(row: any) {
    setEditingId(String(row.id));
    setForm({
      name: row.name ?? "",
      default_interest_rate: String(row.default_interest_rate ?? ""),
      min_term_months: String(row.min_term_months ?? ""),
      max_term_months: String(row.max_term_months ?? ""),
      min_amount: String(row.min_amount ?? ""),
      max_amount: String(row.max_amount ?? ""),
    });
    setMessage("");
    setFailure("");
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setMessage("");
    setFailure("");
    if (!validate()) return;
    setBusy(true);
    const payload = {
      name: form.name.trim(),
      default_interest_rate: Number(form.default_interest_rate),
      min_term_months: Number(form.min_term_months),
      max_term_months: Number(form.max_term_months),
      min_amount: Number(form.min_amount),
      max_amount: Number(form.max_amount),
    };
    try {
      if (editingId) await loanProducts.update(editingId, payload);
      else await loanProducts.create(payload);
      setForm(EMPTY);
      setEditingId(null);
      setMessage("Loan product saved.");
      list.reload();
    } catch (error) {
      setFailure(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Loan products" description="Product rules applied when a loan is created." />
      <Notice tone="danger">{list.error}</Notice>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card title="Products">
          <DataTable
            rows={list.data || []}
            empty={list.loading ? "Loading…" : "No loan products yet."}
            columns={[
              { key: "name", label: "Name" },
              { key: "default_interest_rate", label: "Rate %", render: (r: any) => `${r.default_interest_rate ?? "—"}` },
              { key: "term", label: "Term (months)", render: (r: any) => `${r.min_term_months ?? "—"} – ${r.max_term_months ?? "—"}` },
              { key: "amount", label: "Amount range", render: (r: any) => `${money(r.min_amount)} – ${money(r.max_amount)}` },
              {
                key: "actions",
                label: "",
                render: (r: any) => (
                  <Button variant="outline" onClick={() => startEdit(r)}>
                    Edit
                  </Button>
                ),
              },
            ]}
          />
        </Card>

        <Card title={editingId ? `Edit product #${editingId}` : "Add loan product"}>
          <form onSubmit={onSubmit} className="space-y-3" noValidate>
            <Notice tone="success">{message}</Notice>
            <Notice tone="danger">{failure}</Notice>
            <Field label="Product name" error={errors.name}>
              <Input value={form.name} aria-invalid={Boolean(errors.name)} onChange={(e: any) => set("name", e.target.value)} />
            </Field>
            <Field label="Default interest rate (%)" error={errors.default_interest_rate}>
              <Input type="number" step="0.01" value={form.default_interest_rate} onChange={(e: any) => set("default_interest_rate", e.target.value)} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Min term" error={errors.min_term_months}>
                <Input type="number" value={form.min_term_months} onChange={(e: any) => set("min_term_months", e.target.value)} />
              </Field>
              <Field label="Max term" error={errors.max_term_months}>
                <Input type="number" value={form.max_term_months} onChange={(e: any) => set("max_term_months", e.target.value)} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Min amount" error={errors.min_amount}>
                <Input type="number" value={form.min_amount} onChange={(e: any) => set("min_amount", e.target.value)} />
              </Field>
              <Field label="Max amount" error={errors.max_amount}>
                <Input type="number" value={form.max_amount} onChange={(e: any) => set("max_amount", e.target.value)} />
              </Field>
            </div>
            <div className="flex gap-2">
              <Button type="submit" disabled={busy} className="flex-1">
                {busy ? "Saving…" : editingId ? "Update product" : "Save product"}
              </Button>
              {editingId ? (
                <Button
                  variant="outline"
                  onClick={() => {
                    setEditingId(null);
                    setForm(EMPTY);
                  }}
                >
                  Cancel
                </Button>
              ) : null}
            </div>
          </form>
        </Card>
      </div>
    </>
  );
}
