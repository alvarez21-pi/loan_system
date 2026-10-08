import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, Checkbox, DataTable, Field, Input, InlineNote, MoneyInput, NumberInput, PageHeader, Select, money, percent, useScrollIntoViewOnChange } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { deductionTypes, employeeDeductions, errorMessage, getUser, hasPermission } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/deduction-types")({
  head: () => ({
    meta: [
      { title: "Deduction Types — Microfinance LMS" },
      { name: "description", content: "Configure payroll deductions and employer contributions — no rate is built into the code." },
    ],
  }),
  component: () => (
    <AppShell>
      <DeductionTypesPage />
    </AppShell>
  ),
});

const EMPTY = { name: "", calculation: "fixed", side: "employee", scope: "standard", rate: "", fixed_amount: "", bands: [{ up_to: "", rate: "" }], is_active: true };

function DeductionTypesPage() {
  const user = getUser();
  const canManage = hasPermission(user, "payroll:manage");
  const [tab, setTab] = useState<"standard" | "individual">("standard");
  const list = useResource(() => deductionTypes.list(), []);
  const individual = useResource(() => employeeDeductions.listAll(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Edit lives in a form below the list (not a modal here) — scroll it into
  // view and focus its first field so clicking "Edit" visibly does something.
  const formRef = useScrollIntoViewOnChange<HTMLDivElement>(editingId);

  function startEdit(row: any) {
    setEditingId(String(row.id));
    setForm({
      name: row.name,
      calculation: row.calculation,
      side: row.side,
      scope: row.scope || "standard",
      rate: String(row.rate ?? ""),
      fixed_amount: String(row.fixed_amount ?? ""),
      bands: row.bands && row.bands.length ? row.bands.map((b: any) => ({ up_to: b.up_to ?? "", rate: String(b.rate) })) : [{ up_to: "", rate: "" }],
      is_active: row.is_active,
    });
  }

  function addBand() {
    setForm({ ...form, bands: [...form.bands, { up_to: "", rate: "" }] });
  }
  function updateBand(i: number, key: string, value: string) {
    const bands = form.bands.map((b: any, idx: number) => (idx === i ? { ...b, [key]: value } : b));
    setForm({ ...form, bands });
  }
  function removeBand(i: number) {
    setForm({ ...form, bands: form.bands.filter((_: any, idx: number) => idx !== i) });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      showToast("Name is required.", "danger");
      return;
    }
    setBusy(true);
    const payload: any = { name: form.name.trim(), calculation: form.calculation, side: form.side, scope: form.scope, is_active: form.is_active };
    if (form.calculation === "percentage") payload.rate = Number(form.rate || 0);
    else if (form.calculation === "fixed") payload.fixed_amount = Number(form.fixed_amount || 0);
    else payload.bands = form.bands.map((b: any) => ({ up_to: b.up_to === "" ? null : Number(b.up_to), rate: Number(b.rate || 0) }));
    try {
      if (editingId) await deductionTypes.update(editingId, payload);
      else await deductionTypes.create(payload);
      setForm(EMPTY);
      setEditingId(null);
      showToast("Deduction type saved.", "success");
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  function describe(row: any) {
    if (row.calculation === "fixed") return `${money(row.fixed_amount)} flat`;
    if (row.calculation === "percentage") return `${percent(row.rate)} of gross`;
    return "Progressive bands";
  }

  return (
    <>
      <PageHeader title="Deduction types" />
      <InlineNote tone="danger">{list.error || individual.error}</InlineNote>

      <div className="mb-4 flex flex-wrap gap-2">
        <Button variant={tab === "standard" ? "primary" : "outline"} onClick={() => setTab("standard")}>
          Standard (applies to everyone)
        </Button>
        <Button variant={tab === "individual" ? "primary" : "outline"} onClick={() => setTab("individual")}>
          Individual (assigned)
        </Button>
      </div>

      {tab === "individual" ? (
        <Card title="Individual deductions" description="Edit or stop from the employee's page.">
          <DataTable
            rows={individual.data || []}
            empty={individual.loading ? "Loading…" : "No individual deductions assigned yet."}
            columns={[
              {
                key: "employee_name",
                label: "Employee",
                render: (r: any) => (
                  <Link to="/employees" search={{ edit: r.employee_id }} className="text-primary underline">
                    {r.employee_name}
                  </Link>
                ),
              },
              { key: "deduction_type_name", label: "Type" },
              {
                key: "calculation",
                label: "Amount",
                render: (r: any) => (r.calculation === "percentage" ? `${percent(r.rate)} of gross` : money(r.amount)),
              },
              { key: "remaining_balance", label: "Balance left", render: (r: any) => (r.remaining_balance != null ? money(r.remaining_balance) : "—") },
              { key: "start_month", label: "From" },
              { key: "end_month", label: "Until", render: (r: any) => r.end_month || "—" },
              { key: "is_active", label: "Status", render: (r: any) => (r.is_active ? "Active" : "Stopped") },
            ]}
          />
        </Card>
      ) : (
      <div className={`grid gap-4 ${canManage ? "xl:grid-cols-[1.6fr_1fr]" : ""}`}>
        <Card title="Types">
          <DataTable
            rows={(list.data || []).filter((r: any) => r.scope !== "individual")}
            empty={list.loading ? "Loading…" : "No standard deduction types yet."}
            columns={[
              { key: "name", label: "Name" },
              { key: "scope", label: "Applies to", render: (r: any) => (r.scope === "individual" ? "Individual (assigned)" : "Everyone") },
              { key: "side", label: "Side", render: (r: any) => (r.side === "employer" ? "Employer cost" : "Employee deduction") },
              { key: "calculation", label: "Amount", render: (r: any) => describe(r) },
              { key: "is_active", label: "Active", render: (r: any) => (r.is_active ? "Yes" : "No") },
              {
                key: "actions",
                label: "",
                render: (r: any) => (canManage ? <Button variant="outline" onClick={() => startEdit(r)}>Edit</Button> : null),
              },
            ]}
          />
        </Card>

        {canManage ? (
          <div ref={formRef}>
          <Card title={editingId ? "Edit deduction type" : "Add deduction type"}>
            <form onSubmit={onSubmit} className="space-y-3" noValidate>
              <Field label="Name">
                <Input value={form.name} onChange={(e: any) => setForm({ ...form, name: e.target.value })} />
              </Field>
              <Field label="Side" hint="Employee reduces net pay; employer cost doesn't.">
                <Select value={form.side} onChange={(e: any) => setForm({ ...form, side: e.target.value })}>
                  <option value="employee">Employee deduction</option>
                  <option value="employer">Employer cost</option>
                </Select>
              </Field>
              <Field label="Applies to" hint="Standard applies to everyone; individual, per employee.">
                <Select value={form.scope} onChange={(e: any) => setForm({ ...form, scope: e.target.value })}>
                  <option value="standard">Everyone (standard)</option>
                  <option value="individual">Individual (assigned per employee)</option>
                </Select>
              </Field>
              <Field label="Calculation">
                <Select value={form.calculation} onChange={(e: any) => setForm({ ...form, calculation: e.target.value })}>
                  <option value="fixed">Fixed amount</option>
                  <option value="percentage">Percentage of gross</option>
                  <option value="bands">Progressive bands (e.g. PAYE)</option>
                </Select>
              </Field>
              {form.calculation === "fixed" ? (
                <Field label="Fixed amount">
                  <MoneyInput value={form.fixed_amount} onValueChange={(v) => setForm({ ...form, fixed_amount: v })} />
                </Field>
              ) : null}
              {form.calculation === "percentage" ? (
                <Field label="Rate (%)">
                  <NumberInput decimals={2} value={form.rate} onValueChange={(v) => setForm({ ...form, rate: v })} />
                </Field>
              ) : null}
              {form.calculation === "bands" ? (
                <div className="space-y-2">
                  <p className="text-xs text-muted-foreground">Each band's rate applies only to the slice of salary within it. Leave the last band's "up to" blank for unbounded.</p>
                  {form.bands.map((b: any, i: number) => (
                    <div key={i} className="flex flex-wrap items-end gap-2">
                      <Field label={`Up to (band ${i + 1})`}>
                        <MoneyInput value={b.up_to} onValueChange={(v) => updateBand(i, "up_to", v)} />
                      </Field>
                      <Field label="Rate (%)">
                        <NumberInput decimals={2} value={b.rate} onValueChange={(v) => updateBand(i, "rate", v)} />
                      </Field>
                      {form.bands.length > 1 ? (
                        <Button variant="outline" onClick={() => removeBand(i)}>Remove</Button>
                      ) : null}
                    </div>
                  ))}
                  <Button variant="outline" onClick={addBand}>Add band</Button>
                </div>
              ) : null}
              <Checkbox label="Active" checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} hint="Applies only when active." />
              <div className="flex gap-2">
                <Button type="submit" disabled={busy} className="flex-1">
                  {busy ? "Saving…" : editingId ? "Update type" : "Save type"}
                </Button>
                {editingId ? (
                  <Button variant="outline" onClick={() => { setEditingId(null); setForm(EMPTY); }}>
                    Cancel
                  </Button>
                ) : null}
              </div>
            </form>
          </Card>
          </div>
        ) : null}
      </div>
      )}
    </>
  );
}
