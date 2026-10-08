import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, InlineNote, MoneyInput, PageHeader, StatCard, money } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { capital, errorMessage, getUser, hasPermission } from "../lib/api";
import { localDateString as today } from "../lib/utils";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/capital")({
  head: () => ({
    meta: [
      { title: "Capital — Microfinance LMS" },
      { name: "description", content: "Opening capital, injections, withdrawals, cash on hand and a 6-month projection." },
      { property: "og:title", content: "Capital — Microfinance LMS" },
      { property: "og:description", content: "Capital ledger and cash projection." },
    ],
  }),
  component: () => (
    <AppShell>
      <CapitalPage />
    </AppShell>
  ),
});

function CapitalPage() {
  const user = getUser();
  const canManage = hasPermission(user, "capital:manage");
  const isCeo = user?.role === "ceo";

  const summary = useResource(() => capital.summary(), []);
  const entries = useResource(() => capital.listEntries(), []);
  const projection = useResource(() => capital.projection(), []);

  const [openingForm, setOpeningForm] = useState({ new_value: "", reason: "" });
  const [movementForm, setMovementForm] = useState({ type: "injection", amount: "", date: today(), note: "" });
  const [busy, setBusy] = useState(false);

  const s: any = summary.data || {};
  const hasOpening = Boolean(s.has_opening_entry);

  async function reloadAll() {
    await Promise.all([summary.reload(), entries.reload(), projection.reload()]);
  }

  async function setOpening(e: React.FormEvent) {
    e.preventDefault();
    if (!openingForm.new_value) {
      showToast("Enter the opening capital amount.", "danger");
      return;
    }
    if (hasOpening && !openingForm.reason.trim()) {
      showToast("A reason is required to correct the opening capital figure.", "danger");
      return;
    }
    setBusy(true);
    try {
      await capital.setOpening(Number(openingForm.new_value), openingForm.reason.trim() || undefined);
      showToast(hasOpening ? "Opening capital corrected." : "Opening capital set.", "success");
      setOpeningForm({ new_value: "", reason: "" });
      reloadAll();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function recordMovement(e: React.FormEvent) {
    e.preventDefault();
    if (!movementForm.amount || !movementForm.date) {
      showToast("Enter the amount and date.", "danger");
      return;
    }
    setBusy(true);
    try {
      const fn = movementForm.type === "injection" ? capital.injection : capital.withdrawal;
      await fn(Number(movementForm.amount), movementForm.date, movementForm.note.trim() || undefined);
      showToast(`${movementForm.type === "injection" ? "Injection" : "Withdrawal"} recorded.`, "success");
      setMovementForm({ type: movementForm.type, amount: "", date: today(), note: "" });
      reloadAll();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Capital" description="Cash, capital movements and projection." />
      <InlineNote tone="danger">{summary.error}</InlineNote>

      <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Cash on hand" value={money(s.cash_on_hand)} />
        <StatCard label="Outstanding Balance" value={money(s.outstanding_balance)} hint="What borrowers still owe on active loans — used in the reducing-balance math." />
        <StatCard label="Total Disbursed" value={money(s.total_disbursed)} hint="Lifetime principal ever disbursed (active + closed loans) — a separate figure, never used in the reducing-balance math." />
        <StatCard label="Assets value" value={money(s.assets_value)} />
        <StatCard label="Total worth" value={money(s.total_worth)} hint="Cash + Outstanding Balance + assets" />
      </div>

      <Card title="How this is calculated" className="mb-4">
        <p className="text-sm text-muted-foreground">
          Cash on hand = opening capital ({money(s.opening_capital)}) + injections ({money(s.injections)}) − withdrawals ({money(s.withdrawals)}) +
          repayments received ({money(s.repayments_received)}) − loan principal disbursed ({money(s.loan_principal_disbursed)}) − recorded expenses (
          {money(s.recorded_expenses)}) − finalized payroll ({money(s.finalized_payroll)}). Figures are live, never cached.
        </p>
      </Card>

      {!hasOpening ? (
        canManage ? (
          <Card title="Set opening capital" description="One-time setup — no reason needed the first time." className="mb-4">
            <form onSubmit={setOpening} className="max-w-md space-y-3">
              <Field label="Opening cash amount">
                <MoneyInput value={openingForm.new_value} onValueChange={(v) => setOpeningForm({ ...openingForm, new_value: v })} />
              </Field>
              <Button type="submit" disabled={busy} className="w-full">
                {busy ? "Saving…" : "Set opening capital"}
              </Button>
            </form>
          </Card>
        ) : (
          <InlineNote tone="warning">Opening capital has not been set yet. A CEO, head manager, or finance manager needs to set it up.</InlineNote>
        )
      ) : (
        <div className={`grid gap-4 ${canManage ? "xl:grid-cols-[1.6fr_1fr]" : ""}`}>
          <Card title="Capital history" description="Opening figure and every injection/withdrawal, oldest corrections kept.">
            <DataTable
              rows={entries.data || []}
              empty={entries.loading ? "Loading…" : "No capital entries yet."}
              columns={[
                { key: "entry_type", label: "Type", render: (r: any) => <span className="capitalize">{r.entry_type}</span> },
                {
                  key: "amount",
                  label: "Amount",
                  render: (r: any) => (r.entry_type === "opening" ? money(r.new_value) : money(r.amount)),
                },
                { key: "date", label: "Date", render: (r: any) => r.date || r.created_at?.slice(0, 10) },
                { key: "note", label: "Note / reason", render: (r: any) => r.note || r.reason || "—" },
                { key: "changed_by_name_snapshot", label: "By" },
              ]}
            />
          </Card>

          {canManage ? (
            <div className="space-y-4">
              <Card title="Record injection / withdrawal">
                <form onSubmit={recordMovement} className="space-y-3">
                  <Field label="Type">
                    <select
                      className="lms-input"
                      value={movementForm.type}
                      onChange={(e) => setMovementForm({ ...movementForm, type: e.target.value })}
                    >
                      <option value="injection">Injection</option>
                      <option value="withdrawal">Withdrawal</option>
                    </select>
                  </Field>
                  <Field label="Amount">
                    <MoneyInput value={movementForm.amount} onValueChange={(v) => setMovementForm({ ...movementForm, amount: v })} />
                  </Field>
                  <Field label="Date">
                    <Input type="date" value={movementForm.date} onChange={(e: any) => setMovementForm({ ...movementForm, date: e.target.value })} />
                  </Field>
                  <Field label="Note (optional)">
                    <Input value={movementForm.note} onChange={(e: any) => setMovementForm({ ...movementForm, note: e.target.value })} />
                  </Field>
                  <Button type="submit" disabled={busy} className="w-full">
                    {busy ? "Saving…" : "Record"}
                  </Button>
                </form>
              </Card>

              {isCeo ? (
                <Card title="Correct opening capital" description="CEO only, requires a reason. The previous figure is kept in history.">
                  <form onSubmit={setOpening} className="space-y-3">
                    <Field label="New opening amount">
                      <MoneyInput value={openingForm.new_value} onValueChange={(v) => setOpeningForm({ ...openingForm, new_value: v })} />
                    </Field>
                    <Field label="Reason">
                      <Input value={openingForm.reason} onChange={(e: any) => setOpeningForm({ ...openingForm, reason: e.target.value })} />
                    </Field>
                    <Button type="submit" disabled={busy} className="w-full">
                      {busy ? "Saving…" : "Correct opening capital"}
                    </Button>
                  </form>
                </Card>
              ) : null}
            </div>
          ) : null}
        </div>
      )}

      <Card title="6-month cash projection" description="Estimate — scheduled collections minus the latest finalized payroll and the 3-month average of expenses." className="mt-4">
        <DataTable
          rows={(projection.data as any)?.projection || []}
          empty={projection.loading ? "Loading…" : "No projection available."}
          columns={[
            { key: "month", label: "Month" },
            { key: "expected_collections", label: "Expected collections", render: (r: any) => money(r.expected_collections) },
            { key: "estimated_payroll", label: "Estimated payroll", render: (r: any) => money(r.estimated_payroll) },
            { key: "average_expenses", label: "Average expenses", render: (r: any) => money(r.average_expenses) },
            { key: "projected_cash_end_of_month", label: "Projected cash (month end)", render: (r: any) => money(r.projected_cash_end_of_month) },
          ]}
        />
        {/* A lightweight bar chart: no extra chart library, just scaled divs. */}
        {(projection.data as any)?.projection?.length ? (
          <div className="mt-4 flex items-end gap-3 border-t border-border pt-4" style={{ height: 140 }}>
            {(() => {
              const rows = (projection.data as any).projection;
              const max = Math.max(1, ...rows.map((r: any) => Math.abs(r.projected_cash_end_of_month)));
              return rows.map((r: any) => {
                const heightPct = Math.max(4, (Math.abs(r.projected_cash_end_of_month) / max) * 100);
                return (
                  <div key={r.month} className="flex flex-1 flex-col items-center gap-1">
                    <div
                      className={`w-full rounded-t-sm ${r.projected_cash_end_of_month < 0 ? "bg-destructive" : "bg-primary"}`}
                      style={{ height: `${heightPct}%` }}
                      title={money(r.projected_cash_end_of_month)}
                    />
                    <span className="text-[10px] text-muted-foreground">{r.month}</span>
                  </div>
                );
              });
            })()}
          </div>
        ) : null}
      </Card>
    </>
  );
}
