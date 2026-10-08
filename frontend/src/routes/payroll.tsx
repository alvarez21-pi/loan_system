import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, InlineNote, Modal, MoneyInput, NumberInput, PageHeader, StatusBadge, TextLink, fmtNumber, money, useScrollIntoViewOnChange } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { errorMessage, getUser, hasPermission, payroll } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/payroll")({
  // ?batch=<id> opens that batch's preview (linked from the central Approvals page).
  validateSearch: (search: Record<string, unknown>): { batch?: number | undefined } => ({
    batch: search.batch !== undefined && !Number.isNaN(Number(search.batch)) ? Number(search.batch) : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Payroll — Microfinance LMS" },
      { name: "description", content: "Run monthly payroll batches, preview and finalize them, and issue payslips." },
      { property: "og:title", content: "Payroll — Microfinance LMS" },
      { property: "og:description", content: "Monthly payroll batches — prepare, preview, finalize." },
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
  const user = getUser();
  const search = Route.useSearch();
  const canManage = hasPermission(user, "payroll:manage");

  const list = useResource(() => payroll.list(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [busyKey, setBusyKey] = useState("");
  const [previewId, setPreviewId] = useState<number | null>(search.batch ?? null);
  const [payslipsId, setPayslipsId] = useState<number | null>(null);
  // The line being edited in the preview dialog: { id, employee_name, salary_amount, deductions } as plain numeric strings.
  const [editing, setEditing] = useState<any>(null);
  // One deduction line being adjusted FOR THIS RUN ONLY, in its own dialog:
  // { lineId, dlId, name, salary, otherTotal, mode: "amount"|"percentage", amount, rate }.
  const [editingDl, setEditingDl] = useState<any>(null);
  const [dlBusy, setDlBusy] = useState(false);
  // "Review & finalize" only changed React state to show the preview card
  // further down the page, with nothing visible happening near the click —
  // scroll it into view so the click visibly does something.
  const previewRef = useScrollIntoViewOnChange<HTMLDivElement>(previewId);

  const batches: any[] = list.data || [];
  const preview = batches.find((b) => b.id === previewId) || null;
  const payslipBatch = batches.find((b) => b.id === payslipsId) || null;
  const draftBatches = batches.filter((b) => b.status === "draft");

  function validate() {
    const next: Record<string, string> = {};
    if (!/^\d{4}-\d{2}$/.test(form.period)) next.period = "Select the payroll month.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    setBusy(true);
    try {
      const created: any = await payroll.create({ month: form.period, notes: form.notes || undefined });
      setForm(EMPTY);
      showToast("Payroll batch prepared. Preview and finalize it below when ready.", "success");
      setPreviewId(created?.payroll_batch?.id ?? null);
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  function openPreview(id: number) {
    setPreviewId(id);
    setEditing(null);
  }

  async function saveLine() {
    if (!preview || !editing) return;
    setBusyKey(`line-${editing.id}`);
    try {
      await payroll.editLine(preview.id, editing.id, {
        salary_amount: Number(editing.salary_amount || 0),
        deductions: Number(editing.deductions || 0),
      });
      setEditing(null);
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusyKey("");
    }
  }

  function openDlEdit(line: any, dl: any) {
    const otherTotal = (line.deduction_lines || [])
      .filter((d: any) => d.side === "employee" && d.id !== dl.id)
      .reduce((sum: number, d: any) => sum + Number(d.amount), 0);
    setEditingDl({
      lineId: line.id, dlId: dl.id, name: dl.name,
      salary: Number(line.salary_amount), otherTotal,
      mode: "amount", amount: String(dl.amount), rate: "",
    });
  }

  // Mirrors the backend's clamp (routes/payroll.py: adjust_deduction_line) so
  // the dialog's live preview matches exactly what Save will produce: a
  // percentage is of gross, rounded UP to the whole shilling; either way the
  // result never goes below zero or above what's left after every other
  // deduction on this line.
  function dlPreview(dl: any) {
    const available = Math.max(dl.salary - dl.otherTotal, 0);
    const raw = dl.mode === "percentage"
      ? Math.ceil((dl.salary * Math.min(Math.max(Number(dl.rate) || 0, 0), 100)) / 100)
      : Math.max(Number(dl.amount) || 0, 0);
    const amount = Math.min(Math.max(raw, 0), available);
    return { amount, netPay: dl.salary - (dl.otherTotal + amount) };
  }

  async function saveDeductionLine() {
    if (!preview || !editingDl) return;
    setDlBusy(true);
    try {
      const payload = editingDl.mode === "percentage" ? { rate: Number(editingDl.rate || 0) } : { amount: Number(editingDl.amount || 0) };
      await payroll.adjustDeductionLine(preview.id, editingDl.lineId, editingDl.dlId, payload);
      showToast("Line adjusted for this run only.", "success");
      setEditingDl(null);
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setDlBusy(false);
    }
  }

  async function removeLine(line: any) {
    if (!preview) return;
    if (!window.confirm(`Remove ${line.employee_name} from this payroll batch? They will not be paid in ${preview.month}.`)) return;
    setBusyKey(`line-${line.id}`);
    try {
      await payroll.removeLine(preview.id, line.id);
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusyKey("");
    }
  }

  async function finalize(batch: any) {
    if (!window.confirm(`Finalize the whole ${batch.month} payroll as one action: ${fmtNumber(batch.line_count)} employees, total net pay ${money(batch.total_net)}. This marks it paid — proceed?`)) return;
    setBusyKey(`batch-${batch.id}`);
    try {
      await payroll.finalize(batch.id);
      showToast(`${batch.month} payroll finalized. Payslips are ready to download or send.`, "success");
      setPreviewId(null);
      setEditing(null);
      setPayslipsId(batch.id);
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusyKey("");
    }
  }

  async function cancel(batch: any) {
    if (!window.confirm(`Cancel the ${batch.month} payroll batch? Nothing will be paid — you can run it again afterward.`)) return;
    setBusyKey(`batch-${batch.id}`);
    try {
      await payroll.cancel(batch.id);
      showToast(`${batch.month} payroll cancelled.`, "success");
      setPreviewId(null);
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusyKey("");
    }
  }

  async function downloadPayslip(batch: any, line: any) {
    setBusyKey(`slip-${line.id}`);
    try {
      await payroll.downloadPayslip(line.id, `payslip-${batch.month}-${String(line.employee_name).replace(/\s+/g, "-")}.pdf`);
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusyKey("");
    }
  }

  async function sendPayslip(line: any) {
    const alreadySent = Boolean(line.payslip_sent_at);
    if (alreadySent && !window.confirm(`${line.employee_name} was already sent this payslip. Resend it?`)) return;
    setBusyKey(`send-${line.id}`);
    try {
      const result: any = await payroll.sendPayslip(line.id, alreadySent);
      showToast(result?.message || `Payslip sent to ${line.employee_name}.`, "success");
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusyKey("");
    }
  }

  async function sendAllPayslips(batch: any) {
    const already = (batch.lines || []).filter((l: any) => l.payslip_sent_at).length;
    const warn = already ? ` ${already} of them were already sent — those will be skipped unless you choose to resend.` : "";
    if (!window.confirm(`Email every employee their own payslip for ${batch.month}?${warn}`)) return;
    setBusyKey(`send-all-${batch.id}`);
    try {
      const result: any = await payroll.sendAllPayslips(batch.id);
      const failedNames = (result?.results || []).filter((r: any) => !r.sent).map((r: any) => `${r.employee_name} (${r.message})`);
      showToast(
        `Sent ${result?.sent ?? 0}, failed ${result?.failed ?? 0}` + (failedNames.length ? ` — ${failedNames.join("; ")}` : ""),
        (result?.failed ?? 0) > 0 ? "warning" : "success",
      );
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusyKey("");
    }
  }

  const editable = Boolean(preview && preview.status === "draft");

  return (
    <>
      <PageHeader title="Payroll" description="Monthly salary batches." />
      <InlineNote tone="danger">{list.error}</InlineNote>

      {canManage && draftBatches.length ? (
        <Card title="Draft batches" description={`${fmtNumber(draftBatches.length)} payroll batches not yet finalized`} className="mb-4">
          <DataTable
            rows={draftBatches}
            empty="No draft payroll batches."
            onRowClick={(r) => openPreview(r.id)}
            columns={[
              { key: "month", label: "Month" },
              { key: "line_count", label: "Employees" },
              { key: "total_net", label: "Total net pay", render: (r: any) => money(r.total_net) },
              { key: "creator_name", label: "Prepared by" },
              {
                // Not a button — a step indicator. The row itself is
                // clickable (onRowClick above); the one real action,
                // finalizing, is the clearly-labelled button inside the
                // preview card below, not here.
                key: "actions",
                label: "",
                render: () => <span className="text-xs text-muted-foreground">Not yet reviewed →</span>,
              },
            ]}
          />
        </Card>
      ) : null}

      {preview ? (
        <div ref={previewRef}>
        <Card
          title={`Payroll preview — ${preview.month}`}
          description={`Prepared by ${preview.creator_name || "—"} · ${fmtNumber(preview.line_count)} employees`}
          className="mb-4"
          actions={
            <Button variant="outline" onClick={() => setPreviewId(null)}>
              Close preview
            </Button>
          }
        >
          {preview.status === "cancelled" ? <InlineNote tone="danger">This batch was cancelled.</InlineNote> : null}
          {editable ? (
            <p className="mb-3 text-xs text-muted-foreground">Finalizing confirms every line below — there's no second approval.</p>
          ) : null}

          <DataTable
            rows={preview.lines}
            mobileCard={(r: any) => (
              <div>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{r.employee_name}</p>
                    <p className="text-xs text-muted-foreground">{r.job_title}</p>
                  </div>
                  <p className="shrink-0 font-semibold tabular-nums">{money(r.net_pay)}</p>
                </div>
                <div className="mt-2 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                  <span>Gross {money(r.salary_amount)}</span>
                  <span>Deductions {money(r.deductions)}</span>
                </div>
                {editable ? (
                  <div className="mt-2 flex gap-3">
                    <TextLink onClick={() => setEditing({ id: r.id, employee_name: r.employee_name, salary_amount: String(r.salary_amount), deductions: String(r.deductions) })}>
                      Edit
                    </TextLink>
                    <TextLink tone="danger" onClick={() => removeLine(r)}>Remove</TextLink>
                  </div>
                ) : null}
              </div>
            )}
            columns={[
              {
                key: "employee_name",
                label: "Employee",
                render: (r: any) => (
                  <div>
                    <div>{r.employee_name}</div>
                    <div className="text-xs text-muted-foreground">{r.job_title}</div>
                  </div>
                ),
              },
              { key: "salary_amount", label: "Gross", render: (r: any) => money(r.salary_amount) },
              {
                key: "deductions",
                label: "Deductions",
                render: (r: any) => (
                  <div>
                    <div>{money(r.deductions)}</div>
                    {(r.deduction_lines || []).filter((dl: any) => dl.side === "employee").length > 0 ? (
                      <ul className="mt-1 space-y-1 text-xs text-muted-foreground">
                        {r.deduction_lines.filter((dl: any) => dl.side === "employee").map((dl: any) => (
                          <li key={dl.id}>
                            {dl.name}: {money(dl.amount)}
                            {" "}
                            <span className="rounded bg-muted px-1 py-0.5 text-[10px] uppercase tracking-wide">
                              {dl.scope === "individual" ? "Individual" : "Standard"}
                            </span>
                            {dl.is_adjusted ? (
                              <span className="ml-1 rounded bg-warning/20 px-1 py-0.5 text-[10px] uppercase tracking-wide">Adjusted</span>
                            ) : null}
                            {dl.remaining_after != null ? <span> — {money(dl.remaining_after)} left</span> : null}
                            {editable ? <TextLink onClick={() => openDlEdit(r, dl)}> Edit</TextLink> : null}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {Number(r.employer_cost) > 0 ? (
                      <p className="mt-1 text-xs text-muted-foreground">+ employer cost {money(r.employer_cost)}</p>
                    ) : null}
                  </div>
                ),
              },
              { key: "net_pay", label: "Net pay", render: (r: any) => money(r.net_pay) },
              {
                key: "actions",
                label: "",
                render: (r: any) =>
                  !editable ? null : (
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        onClick={() => setEditing({ id: r.id, employee_name: r.employee_name, salary_amount: String(r.salary_amount), deductions: String(r.deductions) })}
                      >
                        Edit
                      </Button>
                      <Button variant="outline" disabled={busyKey === `line-${r.id}`} onClick={() => removeLine(r)}>
                        Remove
                      </Button>
                    </div>
                  ),
              },
            ]}
          />

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
            <p className="text-sm">
              Total gross <strong>{money(preview.total_gross)}</strong> · Total net pay <strong>{money(preview.total_net)}</strong>
              {Number(preview.total_employer_cost) > 0 ? (
                <>
                  {" "}
                  · Total employer cost <strong>{money(preview.total_employer_cost)}</strong>
                </>
              ) : null}
            </p>
            {editable ? (
              <div className="flex gap-2">
                <Button disabled={busyKey === `batch-${preview.id}` || editing !== null} onClick={() => finalize(preview)}>
                  Finalize (mark paid)
                </Button>
                <Button variant="outline" disabled={busyKey === `batch-${preview.id}`} onClick={() => cancel(preview)}>
                  Cancel batch
                </Button>
              </div>
            ) : null}
          </div>
        </Card>

        {editing ? (
          <Modal title={`Edit ${editing.employee_name}`} description={preview.month} onClose={() => setEditing(null)} size="sm">
            <div className="space-y-3">
              <Field label="Gross salary">
                <MoneyInput value={editing.salary_amount} onValueChange={(v) => setEditing({ ...editing, salary_amount: v })} />
              </Field>
              <Field label="Deductions" hint="Overrides every itemized deduction below with this one total.">
                <MoneyInput value={editing.deductions} onValueChange={(v) => setEditing({ ...editing, deductions: v })} />
              </Field>
              <p className="text-sm text-muted-foreground">
                Net pay: <strong className="text-foreground">{money(Math.max(Number(editing.salary_amount || 0) - Number(editing.deductions || 0), 0))}</strong>
              </p>
              <div className="flex gap-2 pt-1">
                <Button disabled={busyKey === `line-${editing.id}`} onClick={saveLine} className="flex-1">Save</Button>
                <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
              </div>
            </div>
          </Modal>
        ) : null}

        {editingDl ? (
          <Modal title={`Adjust ${editingDl.name}`} description="This run only — the standing deduction is unchanged." onClose={() => setEditingDl(null)} size="sm">
            <div className="space-y-3">
              <div className="flex gap-2">
                <Button
                  compact
                  variant={editingDl.mode === "amount" ? "primary" : "outline"}
                  onClick={() => setEditingDl({ ...editingDl, mode: "amount" })}
                >
                  Amount
                </Button>
                <Button
                  compact
                  variant={editingDl.mode === "percentage" ? "primary" : "outline"}
                  onClick={() => setEditingDl({ ...editingDl, mode: "percentage" })}
                >
                  Percentage
                </Button>
              </div>
              {editingDl.mode === "amount" ? (
                <Field label="Amount">
                  <MoneyInput value={editingDl.amount} onValueChange={(v) => setEditingDl({ ...editingDl, amount: v })} />
                </Field>
              ) : (
                <Field label="Percentage of gross" hint="0 to 100.">
                  <NumberInput decimals={2} value={editingDl.rate} onValueChange={(v) => setEditingDl({ ...editingDl, rate: v })} />
                </Field>
              )}
              {(() => {
                const { amount, netPay } = dlPreview(editingDl);
                return (
                  <p className="text-sm text-muted-foreground">
                    Deduction: <strong className="text-foreground">{money(amount)}</strong>
                    {" "}· Net pay: <strong className="text-foreground">{money(netPay)}</strong>
                  </p>
                );
              })()}
              <div className="flex gap-2 pt-1">
                <Button disabled={dlBusy} onClick={saveDeductionLine} className="flex-1">Save</Button>
                <Button variant="outline" onClick={() => setEditingDl(null)}>Cancel</Button>
              </div>
            </div>
          </Modal>
        ) : null}
        </div>
      ) : null}

      {payslipBatch && payslipBatch.status === "paid" ? (
        <Card
          title={`Payslips — ${payslipBatch.month}`}
          description="One PDF per employee."
          className="mb-4"
          actions={
            <div className="flex gap-2">
              {canManage ? (
                <Button
                  variant="outline"
                  disabled={busyKey === `send-all-${payslipBatch.id}`}
                  onClick={() => sendAllPayslips(payslipBatch)}
                >
                  {busyKey === `send-all-${payslipBatch.id}` ? "Sending…" : "Email all payslips"}
                </Button>
              ) : null}
              <Button variant="outline" onClick={() => setPayslipsId(null)}>
                Close
              </Button>
            </div>
          }
        >
          <DataTable
            rows={payslipBatch.lines}
            columns={[
              { key: "employee_name", label: "Employee" },
              { key: "job_title", label: "Job title" },
              { key: "salary_amount", label: "Gross", render: (r: any) => money(r.salary_amount) },
              {
                key: "deductions",
                label: "Deductions",
                render: (r: any) => (
                  <div>
                    <div>{money(r.deductions)}</div>
                    <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                      {(r.deduction_lines || []).filter((dl: any) => dl.side === "employee").map((dl: any, i: number) => (
                        <li key={i}>{dl.name}: {money(dl.amount)}</li>
                      ))}
                    </ul>
                  </div>
                ),
              },
              { key: "net_pay", label: "Net pay", render: (r: any) => money(r.net_pay) },
              {
                key: "payslip_sent_at",
                label: "Email",
                render: (r: any) => (
                  <span className={r.payslip_sent_at ? "text-success" : "text-muted-foreground"}>
                    {r.payslip_sent_at ? "Sent" : "Not sent"}
                  </span>
                ),
              },
              {
                key: "actions",
                label: "",
                render: (r: any) => (
                  <div className="flex gap-2">
                    <Button variant="outline" disabled={busyKey === `slip-${r.id}`} onClick={() => downloadPayslip(payslipBatch, r)}>
                      Download PDF
                    </Button>
                    {canManage ? (
                      <Button variant="outline" disabled={busyKey === `send-${r.id}`} onClick={() => sendPayslip(r)}>
                        {busyKey === `send-${r.id}` ? "Sending…" : r.payslip_sent_at ? "Resend" : "Send"}
                      </Button>
                    ) : null}
                  </div>
                ),
              },
            ]}
          />
        </Card>
      ) : null}

      <div className={`grid gap-4 ${canManage ? "xl:grid-cols-[1.6fr_1fr]" : ""}`}>
        <Card title="Payroll batches" description={`${fmtNumber(batches.length)} batches`}>
          <DataTable
            rows={batches}
            empty={list.loading ? "Loading…" : "No payroll batches yet."}
            columns={[
              { key: "month", label: "Month" },
              { key: "line_count", label: "Employees" },
              { key: "total_net", label: "Total net pay", render: (r: any) => money(r.total_net) },
              { key: "creator_name", label: "Prepared by" },
              { key: "finalizer_name", label: "Finalized by", render: (r: any) => r.finalizer_name || "—" },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
              {
                key: "actions",
                label: "",
                render: (r: any) => (
                  <div className="flex gap-2">
                    <Button variant="outline" onClick={() => openPreview(r.id)}>
                      Preview
                    </Button>
                    {r.status === "paid" ? (
                      <Button variant="outline" onClick={() => setPayslipsId(r.id)}>
                        Payslips
                      </Button>
                    ) : null}
                  </div>
                ),
              },
            ]}
          />
        </Card>

        {canManage ? (
          <Card title="Run payroll">
            <form onSubmit={onSubmit} className="space-y-3" noValidate>
              <Field label="Payroll month" error={errors.period}>
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
        ) : null}
      </div>
    </>
  );
}
