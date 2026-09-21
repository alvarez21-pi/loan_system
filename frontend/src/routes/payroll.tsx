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
  StatusBadge,
  money,
} from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { errorMessage, payroll } from "../lib/api";

export const Route = createFileRoute("/payroll")({
  head: () => ({
    meta: [
      { title: "Payroll — Microfinance LMS" },
      { name: "description", content: "Run monthly payroll batches and follow their approval status." },
      { property: "og:title", content: "Payroll — Microfinance LMS" },
      { property: "og:description", content: "Monthly payroll batches awaiting approval." },
    ],
  }),
  component: () => (
    <AppShell>
      <PayrollPage />
    </AppShell>
  ),
});

const EMPTY = { period: "", notes: "" };

function PayrollPage() {
  const list = useResource(() => payroll.list(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);

  function validate() {
    const next: Record<string, string> = {};
    if (!/^\d{4}-\d{2}$/.test(form.period)) next.period = "Select the payroll month.";
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
      await payroll.create({ month: form.period, notes: form.notes || undefined });
      setForm(EMPTY);
      setMessage("Payroll batch created and sent for approval.");
      list.reload();
    } catch (error) {
      setFailure(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Payroll" description="Monthly salary batches. Approvals happen on the Approvals page." />
      <Notice tone="danger">{list.error}</Notice>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card title="Payroll batches" description={`${(list.data || []).length} batches`}>
          <DataTable
            rows={list.data || []}
            empty={list.loading ? "Loading…" : "No payroll batches yet."}
            columns={[
              { key: "id", label: "Batch" },
              { key: "month", label: "Month" },
              { key: "employee_id", label: "Employee" },
              { key: "salary_amount", label: "Salary", render: (r: any) => money(r.salary_amount) },
              { key: "net_pay", label: "Net pay", render: (r: any) => money(r.net_pay) },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
            ]}
          />
        </Card>

        <Card title="Run payroll">
          <form onSubmit={onSubmit} className="space-y-3" noValidate>
            <Notice tone="success">{message}</Notice>
            <Notice tone="danger">{failure}</Notice>
            <Field label="Payroll month" error={errors.period} hint="Salaries come from the employee records.">
              <Input type="month" value={form.period} onChange={(e: any) => setForm({ ...form, period: e.target.value })} />
            </Field>
            <Field label="Notes (optional)">
              <Input value={form.notes} onChange={(e: any) => setForm({ ...form, notes: e.target.value })} />
            </Field>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Saving…" : "Create payroll batch"}
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}
