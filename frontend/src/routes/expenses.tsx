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
import { errorMessage, expenses } from "../lib/api";

export const Route = createFileRoute("/expenses")({
  head: () => ({
    meta: [
      { title: "Expenses — Microfinance LMS" },
      { name: "description", content: "Log branch expenses by category and follow their approval status." },
      { property: "og:title", content: "Expenses — Microfinance LMS" },
      { property: "og:description", content: "Branch expense register with approval status." },
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
  const list = useResource(() => expenses.list(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
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
    setMessage("");
    setFailure("");
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
      setMessage("Expense submitted for approval.");
      list.reload();
    } catch (error) {
      setFailure(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  const total = (list.data || []).reduce((sum: number, e: any) => sum + Number(e.amount || 0), 0);

  return (
    <>
      <PageHeader title="Expenses" description="Operating costs recorded per branch." />
      <Notice tone="danger">{list.error}</Notice>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card title="Expense register" description={`${(list.data || []).length} records · total ${money(total)}`}>
          <DataTable
            rows={list.data || []}
            empty={list.loading ? "Loading…" : "No expenses recorded yet."}
            columns={[
              { key: "id", label: "Ref" },
              { key: "description", label: "Description" },
              { key: "category", label: "Category" },
              { key: "amount", label: "Amount", render: (r: any) => money(r.amount) },
              { key: "date", label: "Date" },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
            ]}
          />
        </Card>

        <Card title="Add expense">
          <form onSubmit={onSubmit} className="space-y-3" noValidate>
            <Notice tone="success">{message}</Notice>
            <Notice tone="danger">{failure}</Notice>
            <Field label="Description" error={errors.description}>
              <Input
                value={form.description}
                onChange={(e: any) => setForm({ ...form, description: e.target.value })}
              />
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
              <Input
                type="number"
                step="0.01"
                value={form.amount}
                onChange={(e: any) => setForm({ ...form, amount: e.target.value })}
              />
            </Field>
            <Field label="Expense date" error={errors.expense_date}>
              <Input
                type="date"
                value={form.expense_date}
                onChange={(e: any) => setForm({ ...form, expense_date: e.target.value })}
              />
            </Field>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Saving…" : "Add expense"}
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}
