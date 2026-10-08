import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, InlineNote, MoneyInput, PageHeader, Select, StatusBadge, money, fmtNumber } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { errorMessage, expenses, getUser, hasPermission } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/expenses")({
  head: () => ({
    meta: [
      { title: "Expenses — Microfinance LMS" },
      { name: "description", content: "Log branch expenses by category." },
      { property: "og:title", content: "Expenses — Microfinance LMS" },
      { property: "og:description", content: "Branch expense register." },
    ],
  }),
  component: () => (
    <AppShell>
      <ExpensesPage />
    </AppShell>
  ),
});

const CATEGORIES = ["Utilities", "Transport", "Rent", "Salaries", "Office supplies", "Marketing", "Other"];
const EMPTY = { description: "", category: "", amount: "", expense_date: "" };

function ExpensesPage() {
  const user = getUser();
  // Recorded directly — no approval step (Part 1.1).
  const canCreate = hasPermission(user, "expenses:manage");

  const list = useResource(() => expenses.list(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  function validate() {
    const next: Record<string, string> = {};
    if (!form.description.trim()) next.description = "Describe the expense.";
    if (!form.category) next.category = "Select a category.";
    if (!Number(form.amount) || Number(form.amount) <= 0) next.amount = "Enter the amount.";
    if (!form.expense_date) next.expense_date = "Select the expense date.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    setBusy(true);
    try {
      await expenses.create({
        description: form.description.trim(),
        category: form.category,
        amount: Number(form.amount),
        date: form.expense_date,
      });
      setForm(EMPTY);
      showToast("Expense recorded.", "success");
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  const rows = list.data || [];
  const total = rows.reduce((sum: number, e: any) => sum + Number(e.amount || 0), 0);

  return (
    <>
      <PageHeader title="Expenses" description="Operating costs recorded per branch." />
      <InlineNote tone="danger">{list.error}</InlineNote>

      <div className={`grid gap-4 ${canCreate ? "xl:grid-cols-[1.6fr_1fr]" : ""}`}>
        <Card title="Expense register" description={`${fmtNumber(rows.length)} records · total ${money(total)}`}>
          <DataTable
            rows={rows}
            empty={list.loading ? "Loading…" : "No expenses recorded yet."}
            columns={[
              { key: "description", label: "Description" },
              { key: "category", label: "Category" },
              { key: "amount", label: "Amount", render: (r: any) => money(r.amount) },
              { key: "date", label: "Date" },
              { key: "created_by_name", label: "Added by" },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
            ]}
            mobileCard={(r: any) => (
              <div>
                <div className="flex items-start justify-between gap-3">
                  <p className="min-w-0 truncate font-medium">{r.description}</p>
                  <p className="shrink-0 font-semibold tabular-nums">{money(r.amount)}</p>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{r.category}</p>
                <div className="mt-2 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                  <StatusBadge status={r.status} />
                  <span>{r.date}</span>
                </div>
              </div>
            )}
          />
        </Card>

        {canCreate ? (
          <Card title="Add expense">
            <form onSubmit={onSubmit} className="space-y-3" noValidate>
              <Field label="Description" error={errors.description}>
                <Input value={form.description} onChange={(e: any) => setForm({ ...form, description: e.target.value })} />
              </Field>
              <Field label="Category" error={errors.category}>
                <Select value={form.category} onChange={(e: any) => setForm({ ...form, category: e.target.value })}>
                  <option value="">Select category</option>
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Amount" error={errors.amount}>
                <MoneyInput value={form.amount} onValueChange={(v) => setForm({ ...form, amount: v })} />
              </Field>
              <Field label="Expense date" error={errors.expense_date}>
                <Input type="date" value={form.expense_date} onChange={(e: any) => setForm({ ...form, expense_date: e.target.value })} />
              </Field>
              <Button type="submit" disabled={busy} className="w-full">
                {busy ? "Saving…" : "Add expense"}
              </Button>
            </form>
          </Card>
        ) : null}
      </div>
    </>
  );
}
