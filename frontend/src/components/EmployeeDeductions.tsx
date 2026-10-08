import { useEffect, useState } from "react";
import { Button, Card, Field, Input, MoneyInput, NumberInput, Select, money } from "./lms-ui";
import { deductionTypes, employeeDeductions, errorMessage } from "../lib/api";
import { showToast } from "../lib/toast";

const EMPTY = { deduction_type_id: "", calculation: "fixed", amount: "", rate: "", start_month: "", end_month: "", remaining_balance: "" };

/** One employee's individual deductions (loan repayment, salary advance,
 * uniform...) — a "Deductions" section embedded in the employee's own
 * edit form. Standard (company-wide) deductions are configured once on
 * the Deduction Types page and never listed per employee. */
export function EmployeeDeductions({ employeeId }: { employeeId: number }) {
  const [types, setTypes] = useState<any[]>([]);
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<any>(EMPTY);
  const [busy, setBusy] = useState(false);

  async function reload() {
    setLoading(true);
    try {
      const [typesRes, rowsRes]: any = await Promise.all([deductionTypes.list(), employeeDeductions.list(employeeId)]);
      setTypes((typesRes.data || []).filter((t: any) => t.scope === "individual" && t.is_active));
      setRows(rowsRes.data || []);
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeId]);

  function startAdd() {
    setForm(EMPTY);
    setEditingId(null);
    setAdding(true);
  }
  function startEdit(row: any) {
    setForm({
      deduction_type_id: String(row.deduction_type_id),
      calculation: row.calculation,
      amount: row.amount != null ? String(row.amount) : "",
      rate: row.rate != null ? String(row.rate) : "",
      start_month: row.start_month,
      end_month: row.end_month || "",
      remaining_balance: row.remaining_balance != null ? String(row.remaining_balance) : "",
    });
    setEditingId(row.id);
    setAdding(true);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.deduction_type_id) {
      showToast("Choose a deduction type.", "danger");
      return;
    }
    if (!form.start_month) {
      showToast("Choose a start month.", "danger");
      return;
    }
    setBusy(true);
    const payload: any = {
      deduction_type_id: Number(form.deduction_type_id), calculation: form.calculation,
      start_month: form.start_month, end_month: form.end_month || undefined,
      remaining_balance: form.remaining_balance === "" ? undefined : Number(form.remaining_balance),
    };
    if (form.calculation === "percentage") payload.rate = Number(form.rate || 0);
    else payload.amount = Number(form.amount || 0);
    try {
      if (editingId) await employeeDeductions.update(editingId, payload);
      else await employeeDeductions.create({ ...payload, employee_id: employeeId });
      showToast(editingId ? "Deduction updated." : "Deduction added.", "success");
      setAdding(false);
      reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function stop(row: any) {
    if (!window.confirm(`Stop "${row.deduction_type_name}" for this employee? Its history is kept.`)) return;
    try {
      await employeeDeductions.stop(row.id);
      showToast("Deduction stopped.", "success");
      reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  const active = rows.filter((r) => r.is_active);

  return (
    <Card title="Deductions" description="Assigned to this employee only.">
      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="space-y-2">
          {active.length === 0 ? <p className="text-sm text-muted-foreground">No individual deductions.</p> : null}
          {active.map((row) => (
            <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-2 text-sm">
              <div>
                <div className="font-medium">
                  {row.deduction_type_name} — {row.calculation === "percentage" ? `${row.rate}% of gross` : money(row.amount)}
                  {row.remaining_balance != null ? ` · ${money(row.remaining_balance)} left` : ""}
                </div>
                <div className="text-xs text-muted-foreground">
                  From {row.start_month}{row.end_month ? ` to ${row.end_month}` : ""}
                </div>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => startEdit(row)}>Edit</Button>
                <Button variant="outline" onClick={() => stop(row)}>Stop</Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {adding ? (
        <form onSubmit={onSubmit} className="mt-4 space-y-3 border-t border-border pt-4">
          <Field label="Type">
            <Select value={form.deduction_type_id} onChange={(e: any) => setForm({ ...form, deduction_type_id: e.target.value })}>
              <option value="">Select…</option>
              {types.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </Select>
          </Field>
          <Field label="Amount type">
            <Select value={form.calculation} onChange={(e: any) => setForm({ ...form, calculation: e.target.value })}>
              <option value="fixed">Fixed amount</option>
              <option value="percentage">Percentage of gross</option>
            </Select>
          </Field>
          {form.calculation === "fixed" ? (
            <Field label="Amount per month">
              <MoneyInput value={form.amount} onValueChange={(v) => setForm({ ...form, amount: v })} />
            </Field>
          ) : (
            <Field label="Percentage of gross" hint="0 to 100.">
              <NumberInput decimals={2} value={form.rate} onValueChange={(v) => setForm({ ...form, rate: v })} />
            </Field>
          )}
          <Field label="Start month">
            <Input type="month" value={form.start_month} onChange={(e: any) => setForm({ ...form, start_month: e.target.value })} />
          </Field>
          <Field label="End month" hint="Leave blank if using a total balance instead.">
            <Input type="month" value={form.end_month} onChange={(e: any) => setForm({ ...form, end_month: e.target.value })} />
          </Field>
          <Field label="Total balance to repay" hint="Leave blank if using an end month.">
            <MoneyInput value={form.remaining_balance} onValueChange={(v) => setForm({ ...form, remaining_balance: v })} />
          </Field>
          <div className="flex gap-2">
            <Button type="submit" disabled={busy}>{busy ? "Saving…" : editingId ? "Save changes" : "Add deduction"}</Button>
            <Button type="button" variant="outline" onClick={() => setAdding(false)}>Cancel</Button>
          </div>
        </form>
      ) : (
        <Button variant="outline" className="mt-4" onClick={startAdd}>Add deduction for this employee</Button>
      )}
    </Card>
  );
}

export default EmployeeDeductions;
