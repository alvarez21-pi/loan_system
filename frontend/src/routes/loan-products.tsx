import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, InlineNote, MoneyInput, NumberInput, PageHeader, fmtNumber, money, percent, useScrollIntoViewOnChange } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { errorMessage, getUser, hasPermission, loanProducts } from "../lib/api";
import { showToast } from "../lib/toast";

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

/** "1,000 – 5,000", "from 1,000", "up to 5,000" or "No limit" — a blank limit is simply not enforced. */
function range(min: unknown, max: unknown, fmt: (v: unknown) => string, unit: string) {
  const lo = min === null || min === undefined ? null : fmt(min);
  const hi = max === null || max === undefined ? null : fmt(max);
  if (lo && hi) return `${lo} – ${hi}${unit}`;
  if (lo) return `from ${lo}${unit}`;
  if (hi) return `up to ${hi}${unit}`;
  return "No limit";
}

function LoanProductsPage() {
  const user = getUser();
  const canManage = hasPermission(user, "loan_products:manage");
  const list = useResource(() => loanProducts.list(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const formRef = useScrollIntoViewOnChange<HTMLDivElement>(editingId);

  function set(key: string, value: string) {
    setForm({ ...form, [key]: value });
  }

  // Term and amount limits are all optional: blank means "no restriction".
  function validate() {
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "Product name is required.";
    const rate = Number(form.default_interest_rate);
    if (form.default_interest_rate === "" || Number.isNaN(rate) || rate < 0) next.default_interest_rate = "Enter a valid monthly rate (%).";
    const has = (v: string) => v !== "" && v !== null && v !== undefined;
    if (has(form.min_term_months) && Number(form.min_term_months) < 1) next.min_term_months = "Must be at least 1 month.";
    if (has(form.max_term_months) && Number(form.max_term_months) < 1) next.max_term_months = "Must be at least 1 month.";
    if (has(form.min_term_months) && has(form.max_term_months) && Number(form.max_term_months) < Number(form.min_term_months))
      next.max_term_months = "Maximum term cannot be less than the minimum.";
    if (has(form.min_amount) && has(form.max_amount) && Number(form.max_amount) < Number(form.min_amount))
      next.max_amount = "Maximum amount cannot be less than the minimum.";
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
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    setBusy(true);
    // A blank limit is sent as null so an edit can also clear a limit that was set before.
    const optional = (v: string) => (v === "" || v === null || v === undefined ? null : Number(v));
    const payload = {
      name: form.name.trim(),
      default_interest_rate: Number(form.default_interest_rate),
      min_term_months: optional(form.min_term_months),
      max_term_months: optional(form.max_term_months),
      min_amount: optional(form.min_amount),
      max_amount: optional(form.max_amount),
    };
    try {
      if (editingId) await loanProducts.update(editingId, payload);
      else await loanProducts.create(payload);
      setForm(EMPTY);
      setEditingId(null);
      showToast("Loan product saved.", "success");
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Loan products" description="Rules applied automatically to new loans." />
      <InlineNote tone="danger">{list.error}</InlineNote>

      <div className={`grid gap-4 ${canManage ? "xl:grid-cols-[1.6fr_1fr]" : ""}`}>
        <Card title="Products">
          <DataTable
            rows={list.data || []}
            empty={list.loading ? "Loading…" : "No loan products yet."}
            columns={[
              { key: "name", label: "Name" },
              { key: "default_interest_rate", label: "Monthly Rate (%)", render: (r: any) => percent(r.default_interest_rate) },
              { key: "term", label: "Term (months)", render: (r: any) => range(r.min_term_months, r.max_term_months, fmtNumber, " months") },
              { key: "amount", label: "Amount range", render: (r: any) => range(r.min_amount, r.max_amount, money, "") },
              {
                key: "actions",
                label: "",
                render: (r: any) =>
                  canManage ? (
                    <Button variant="outline" onClick={() => startEdit(r)}>
                      Edit
                    </Button>
                  ) : null,
              },
            ]}
          />
        </Card>

        {canManage ? (
          <div ref={formRef}>
          <Card title={editingId ? "Edit loan product" : "Add loan product"} description="Leave a limit blank for no restriction.">
            <form onSubmit={onSubmit} className="space-y-3" noValidate>
              <Field label="Product name" error={errors.name}>
                <Input value={form.name} aria-invalid={Boolean(errors.name)} onChange={(e: any) => set("name", e.target.value)} />
              </Field>
              <Field label="Default Monthly Interest Rate (%)" error={errors.default_interest_rate}>
                <NumberInput decimals={2} value={form.default_interest_rate} onValueChange={(v) => set("default_interest_rate", v)} />
              </Field>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field label="Min term (months)" error={errors.min_term_months} hint="Optional">
                  <NumberInput integer value={form.min_term_months} onValueChange={(v) => set("min_term_months", v)} />
                </Field>
                <Field label="Max term (months)" error={errors.max_term_months} hint="Optional">
                  <NumberInput integer value={form.max_term_months} onValueChange={(v) => set("max_term_months", v)} />
                </Field>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field label="Min amount" error={errors.min_amount} hint="Optional">
                  <MoneyInput value={form.min_amount} onValueChange={(v) => set("min_amount", v)} />
                </Field>
                <Field label="Max amount" error={errors.max_amount} hint="Optional">
                  <MoneyInput value={form.max_amount} onValueChange={(v) => set("max_amount", v)} />
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
        ) : null}
      </div>
    </>
  );
}
