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
import { employees, errorMessage } from "../lib/api";

export const Route = createFileRoute("/employees")({
  head: () => ({
    meta: [
      { title: "Employees — Microfinance LMS" },
      { name: "description", content: "Staff register with roles, salaries and hire dates for payroll processing." },
      { property: "og:title", content: "Employees — Microfinance LMS" },
      { property: "og:description", content: "Staff register with roles and salaries." },
    ],
  }),
  component: () => (
    <AppShell>
      <EmployeesPage />
    </AppShell>
  ),
});

const ROLES = ["Loan Officer", "Branch Accountant", "Branch Manager", "Supervisor", "Cashier", "Administrator"];
const EMPTY = { name: "", phone: "", role: "", salary: "", hire_date: "" };

function EmployeesPage() {
  const list = useResource(() => employees.list(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);

  function validate() {
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "Enter the employee name.";
    if (!/^\+?\d{9,15}$/.test(form.phone.replace(/\s/g, ""))) next.phone = "Enter a valid phone number.";
    if (!form.role) next.role = "Select a role.";
    if (!Number(form.salary) || Number(form.salary) <= 0) next.salary = "Enter the monthly salary.";
    if (!form.hire_date) next.hire_date = "Select the hire date.";
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
      await employees.create({
        name: form.name.trim(),
        phone: form.phone.trim(),
        role: form.role,
        salary: Number(form.salary),
        start_date: form.hire_date,
      });
      setForm(EMPTY);
      setMessage("Employee added.");
      list.reload();
    } catch (error) {
      setFailure(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  const payrollTotal = (list.data || []).reduce((s: number, e: any) => s + Number(e.salary || 0), 0);

  return (
    <>
      <PageHeader title="Employees" description="Staff records used for payroll." />
      <Notice tone="danger">{list.error}</Notice>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card
          title="Staff list"
          description={`${(list.data || []).length} employees · monthly salaries ${money(payrollTotal)}`}
        >
          <DataTable
            rows={list.data || []}
            empty={list.loading ? "Loading…" : "No employees yet."}
            columns={[
              { key: "id", label: "ID" },
              { key: "name", label: "Name", render: (r: any) => r.name || r.full_name || "—" },
              { key: "phone", label: "Phone" },
              { key: "role", label: "Role" },
              { key: "salary", label: "Salary", render: (r: any) => money(r.salary) },
              { key: "start_date", label: "Hired" },
            ]}
          />
        </Card>

        <Card title="Add employee">
          <form onSubmit={onSubmit} className="space-y-3" noValidate>
            <Notice tone="success">{message}</Notice>
            <Notice tone="danger">{failure}</Notice>
            <Field label="Full name" error={errors.name}>
              <Input value={form.name} onChange={(e: any) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field label="Phone" error={errors.phone}>
              <Input value={form.phone} onChange={(e: any) => setForm({ ...form, phone: e.target.value })} />
            </Field>
            <Field label="Role" error={errors.role}>
              <Select value={form.role} onChange={(e: any) => setForm({ ...form, role: e.target.value })}>
                <option value="">Select role</option>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Monthly salary" error={errors.salary}>
              <Input
                type="number"
                step="0.01"
                value={form.salary}
                onChange={(e: any) => setForm({ ...form, salary: e.target.value })}
              />
            </Field>
            <Field label="Hire date" error={errors.hire_date}>
              <Input
                type="date"
                value={form.hire_date}
                onChange={(e: any) => setForm({ ...form, hire_date: e.target.value })}
              />
            </Field>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Saving…" : "Add employee"}
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}
