import { useState } from "react";
import { Button, Field, Input, InlineNote, MoneyInput, money, useMobileBottomBarOffset } from "./lms-ui";
import { errorMessage, getUser, hasPermission, loans, repayments } from "../lib/api";
import { localDateString as today } from "../lib/utils";
import { showToast } from "../lib/toast";

/**
 * The one repayment-recording form. Used identically whether it's reached
 * from a loan's own detail page or from the general Repayments page, where
 * the loan is picked first (Part 5.1) — both call this same component,
 * which calls the same `repayments.create()` endpoint. Neither entry point
 * re-implements the logic.
 */
export function RepaymentForm({ loan, onRecorded }: { loan: any; onRecorded: (result: any) => void }) {
  const [form, setForm] = useState({ amount_paid: "", payment_date: today() });
  const [busy, setBusy] = useState(false);
  // Phase 2 item 5: one key per pending submission. A failed/timed-out
  // attempt reuses the SAME key on retry (so the backend can recognize a
  // resend); a successful submission rotates it so the NEXT payment gets
  // its own key.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());
  // Phone pass: the main action button here gets a sticky bottom bar so the
  // on-screen keyboard never hides it - raises the floating toast stack to
  // clear it too, for as long as this form is on screen.
  useMobileBottomBarOffset(true);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const amount = Number(form.amount_paid);
    if (!amount || amount <= 0) {
      showToast("Enter the amount paid.", "danger");
      return;
    }
    if (!form.payment_date) {
      showToast("Select the payment date.", "danger");
      return;
    }
    if (amount > Number(loan.settlement_amount)) {
      showToast(`The most you can pay today to settle this loan is ${money(loan.settlement_amount)}.`, "danger");
      return;
    }
    setBusy(true);
    try {
      const result: any = await repayments.create({
        loan_id: loan.id, amount_paid: amount, payment_date: form.payment_date, idempotency_key: idempotencyKey,
      });
      setForm({ amount_paid: "", payment_date: today() });
      setIdempotencyKey(crypto.randomUUID());
      onRecorded(result);
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={onSubmit} className="space-y-3" noValidate>
        <Field
          label="Amount paid"
          hint={`Outstanding balance ${money(loan.outstanding_balance)} · to settle in full today: ${money(loan.settlement_amount)}`}
        >
          <MoneyInput value={form.amount_paid} onValueChange={(v) => setForm({ ...form, amount_paid: v })} />
        </Field>
        <Field label="Payment date">
          <Input type="date" value={form.payment_date} onChange={(e: any) => setForm({ ...form, payment_date: e.target.value })} />
        </Field>
        <div className="lms-sticky-bottom-bar">
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Saving…" : "Record repayment"}
          </Button>
        </div>
      </form>
      <SettleLoanPanel loan={loan} onRecorded={onRecorded} />
    </div>
  );
}

/**
 * Early full settlement (Part 4). The rule itself: settlement = outstanding
 * principal + the full interest for the current period - unchanged. Only a
 * Loans Manager/Head Manager/CEO additionally sees the discount field; a
 * Maker/Checker still sees and can use the plain "Settle today" button with
 * no discount.
 */
function SettleLoanPanel({ loan, onRecorded }: { loan: any; onRecorded: (result: any) => void }) {
  const user = getUser();
  const canDiscount = hasPermission(user, "settlement:discount");
  const [discount, setDiscount] = useState("");
  const [reason, setReason] = useState("");
  const [paymentDate, setPaymentDate] = useState(today());
  const [busy, setBusy] = useState(false);
  // Phase 2 item 5: same reuse-until-success key as RepaymentForm above.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());

  const openRow = (loan.schedules || []).find((r: any) => ["upcoming", "partial", "missed"].includes(r.status));
  const principal = Number(loan.outstanding_balance || 0);
  const interest = Number(openRow?.interest_portion || 0);
  // Phase 2 item 6: the undiscounted total is the backend's own
  // settlement_amount field, never principal + interest re-derived here.
  // Only the discount (an amount the backend hasn't seen yet, mid-entry) is
  // subtracted client-side for a live preview — the actual amount charged
  // is always whatever the backend's response reports, never this value.
  const backendSettlement = Number(loan.settlement_amount || 0);
  // Any discount from 0 up to the full amount needed to settle — not
  // capped at the period's interest; a big enough discount also forgives
  // some principal, not just interest.
  const discountAmount = Math.min(Math.max(Number(discount) || 0, 0), backendSettlement);
  const totalToSettle = Math.max(backendSettlement - discountAmount, 0);
  const discountExceedsInterest = discountAmount > interest;

  async function settle() {
    if (discountAmount > 0 && !reason.trim()) {
      showToast("A reason is required to apply a settlement discount.", "danger");
      return;
    }
    setBusy(true);
    try {
      const result = await loans.settle(loan.id, {
        payment_date: paymentDate,
        discount: discountAmount > 0 ? discountAmount : undefined,
        discount_reason: discountAmount > 0 ? reason.trim() : undefined,
        idempotency_key: idempotencyKey,
      });
      setDiscount("");
      setReason("");
      setIdempotencyKey(crypto.randomUUID());
      showToast("Loan settled.", "success");
      onRecorded(result);
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-md border border-border p-3 space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Settle this loan today</p>
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-muted-foreground">Principal</dt>
          <dd className="font-medium">{money(principal)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Interest (this period)</dt>
          <dd className="font-medium">{money(interest)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Discount</dt>
          <dd className="font-medium">{money(discountAmount)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Total to settle</dt>
          <dd className="font-medium">{money(totalToSettle)}</dd>
        </div>
      </dl>
      <Field label="Settlement date">
        <Input type="date" value={paymentDate} onChange={(e: any) => setPaymentDate(e.target.value)} />
      </Field>
      {canDiscount ? (
        <>
          <Field label="Discount (optional)" hint={`Up to the full amount needed to settle (${money(backendSettlement)}).`}>
            <MoneyInput value={discount} onValueChange={setDiscount} />
          </Field>
          {discountExceedsInterest ? (
            <InlineNote tone="warning">
              This discount is larger than this period's interest ({money(interest)}) — the extra also forgives part of the principal, not just interest.
            </InlineNote>
          ) : null}
          {Number(discount) > 0 ? (
            <Field label="Reason for the discount" hint="Required whenever a discount is applied.">
              <Input value={reason} onChange={(e: any) => setReason(e.target.value)} />
            </Field>
          ) : null}
        </>
      ) : null}
      <Button variant="outline" disabled={busy} onClick={settle} className="w-full">
        {busy ? "Settling…" : `Settle today for ${money(totalToSettle)}`}
      </Button>
    </div>
  );
}
