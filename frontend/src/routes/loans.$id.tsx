import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import AppShell from "../components/AppShell";
import { RepaymentForm } from "../components/RepaymentForm";
import {
  Button,
  Card,
  DataTable,
  InlineNote,
  PageHeader,
  StatusBadge,
  fmtNumber,
  money,
  percent,
} from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { errorMessage, getUser, hasPermission, loans } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/loans/$id")({
  head: () => ({
    meta: [
      { title: "Loan Detail — Microfinance LMS" },
      { name: "description", content: "Loan schedule, repayment history and delivery options." },
      { property: "og:title", content: "Loan Detail — Microfinance LMS" },
      { property: "og:description", content: "Repayment schedule, history and borrower delivery." },
    ],
  }),
  component: () => (
    <AppShell>
      <LoanDetail />
    </AppShell>
  ),
});

const OPEN = ["upcoming", "partial", "missed"];

function LoanDetail() {
  const { id } = Route.useParams();
  const user = getUser();
  const detail = useResource(() => loans.get(id), [id]);
  const loan: any = detail.data;

  const [downloading, setDownloading] = useState(false);
  const [deciding, setDeciding] = useState("");

  // Only against a loan that is live, and only for a user with repayments:record.
  const canRecordRepayment = hasPermission(user, "repayments:record") && loan?.status === "active";

  // Balance after each instalment, derived from the schedule itself: the
  // principal still to be repaid by the instalments that follow it.
  const schedule = useMemo(() => {
    const rows: any[] = loan?.schedules || [];
    let after = 0;
    const balances: number[] = [];
    for (let i = rows.length - 1; i >= 0; i--) {
      balances[i] = after;
      after += Number(rows[i].principal_portion || 0);
    }
    return rows.map((row, i) => ({ ...row, number: i + 1, balance_after: balances[i] }));
  }, [loan]);

  function onRepaymentRecorded(result: any) {
    const after = result?.loan;
    showToast(
      after?.status === "closed"
        ? "Repayment recorded. This loan is now fully paid."
        : `Repayment recorded. The remaining schedule was recalculated on the new balance of ${money(after?.outstanding_balance)}.`,
      "success",
    );
    detail.reload();
  }

  async function decide(action: "approve" | "reject") {
    const borrower = loan.borrower_name || "this borrower";
    const question =
      action === "approve"
        ? `This will activate Loan #${loan.id} for ${borrower} — ${money(loan.principal_amount)} at ${percent(loan.interest_rate)} per month over ${fmtNumber(loan.term_months)} months, and send the schedule to the borrower. Approve?`
        : `This will reject Loan #${loan.id} for ${borrower}. Are you sure?`;
    if (!window.confirm(question)) return;
    let rejection_reason: string | undefined;
    if (action === "reject") {
      rejection_reason = window.prompt("Reason for rejection:") || undefined;
      if (!rejection_reason) return;
    }
    setDeciding(action);
    try {
      await loans[action](loan.id, action === "reject" ? { rejection_reason } : undefined);
      showToast(`Loan #${loan.id} ${action === "approve" ? "approved" : "rejected"}.`, "success");
      detail.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setDeciding("");
    }
  }

  async function downloadPdf() {
    setDownloading(true);
    try {
      await loans.downloadSchedule(loan.id);
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setDownloading(false);
    }
  }

  function sendWhatsApp() {
    const borrowerPhone = String(loan?.borrower?.phone || "").replace(/[^0-9]/g, "");
    const text = `Hello ${loan?.borrower?.name || ""}, here is the repayment schedule for Loan #${loan?.id}. A PDF copy is attached — please download it from the link we sent, or ask us to resend it.`;
    downloadPdf();
    window.open(`https://wa.me/${borrowerPhone}?text=${encodeURIComponent(text)}`, "_blank", "noopener,noreferrer");
  }

  // Server-computed from the current reconciled schedule — never re-derived
  // on the client (totals must reflect paid rows plus recalculated remaining
  // rows, not the original plan).
  const totals = loan?.totals;
  const openCount = totals ? totals.remaining_instalments : schedule.filter((r: any) => OPEN.includes(r.status)).length;

  return (
    <>
      <PageHeader
        title={loan ? `Loan #${loan.id}${loan.borrower_name ? ` — ${loan.borrower_name}` : ""}` : "Loan"}
        description="Repayment schedule, history and delivery."
        actions={
          <Link to="/loans" className="lms-btn lms-btn-outline">
            Back to loans
          </Link>
        }
      />
      <InlineNote tone="danger">{detail.error}</InlineNote>

      {detail.loading && !loan ? (
        <Card>Loading…</Card>
      ) : !loan ? (
        <Card>Loan not found.</Card>
      ) : (
        <div className="space-y-4">
          <Card title="Overview">
            {/* Phone pass: 2 columns even below `sm` (360-412px) so this
                never reads as one long single-column list on a small screen. */}
            <dl className="grid grid-cols-2 gap-3 xl:grid-cols-4 text-sm">
              {[
                ["Borrower", loan.borrower ? (
                  <Link key="b" to="/borrowers/$id" params={{ id: String(loan.borrower.id) }} className="text-primary underline">
                    {loan.borrower.name}
                  </Link>
                ) : loan.borrower_name],
                ["Product", loan.product_name || "Negotiated rate"],
                ["Status", <StatusBadge key="status" status={loan.status} reason={loan.rejection_reason} />],
                ["Principal", money(loan.principal_amount)],
                ["Monthly Interest Rate", `${percent(loan.interest_rate)} per month`],
                ["Term", `${fmtNumber(loan.term_months)} months`],
                ["Start date", loan.start_date],
                ["Outstanding balance", money(loan.outstanding_balance)],
                ["Instalment rounding step", `${fmtNumber(loan.rounding_step)} shillings`],
                ["Paid to date", totals ? money(totals.paid_to_date) : "—"],
                ["Remaining instalments", totals ? fmtNumber(totals.remaining_instalments) : "—"],
                ["Created by", loan.creator_name_snapshot || "—"],
                ["Approved by", loan.approver_name_snapshot || "—"],
              ].map(([label, value]) => (
                <div key={String(label)}>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
                  <dd className="font-medium">{value ?? "—"}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-4 flex flex-wrap gap-2">
              {/* Available in every status, draft/pending included — not only after approval. */}
              <Button variant="outline" disabled={downloading} onClick={downloadPdf}>
                {downloading ? "Preparing PDF…" : "Download Schedule (PDF)"}
              </Button>
              {loan.borrower?.phone ? (
                <Button variant="outline" onClick={sendWhatsApp}>
                  Send via WhatsApp
                </Button>
              ) : null}
              {loan.can_decide && loan.status === "pending_approval" ? (
                <>
                  <Button disabled={deciding !== ""} onClick={() => decide("approve")}>
                    Approve loan
                  </Button>
                  <Button variant="outline" disabled={deciding !== ""} onClick={() => decide("reject")}>
                    Reject loan
                  </Button>
                </>
              ) : null}
            </div>
          </Card>

          <Card
            title="Repayment schedule"
            description={
              loan.status === "pending_approval"
                ? "Visible once the loan is approved."
                : `${openCount} instalment${openCount === 1 ? "" : "s"} still to pay.`
            }
          >
            {totals ? (
              <dl className="mb-4 grid gap-3 sm:grid-cols-3 text-sm">
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Total of schedule</dt>
                  <dd className="font-medium">{money(totals.total_payable)}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Paid to date</dt>
                  <dd className="font-medium">{money(totals.paid_to_date)}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Still to pay</dt>
                  <dd className="font-medium">{money(totals.total_payable - totals.paid_to_date)}</dd>
                </div>
              </dl>
            ) : null}
            <DataTable
              rows={schedule}
              empty="No schedule generated."
              columns={[
                { key: "number", label: "#", render: (r: any) => fmtNumber(r.number) },
                { key: "due_date", label: "Due date" },
                { key: "principal_portion", label: "Principal", render: (r: any) => money(r.principal_portion) },
                { key: "interest_portion", label: "Interest", render: (r: any) => money(r.interest_portion) },
                { key: "expected_amount", label: "Payment", render: (r: any) => money(r.expected_amount) },
                { key: "balance_after", label: "Balance after", render: (r: any) => money(r.balance_after) },
                {
                  key: "status",
                  label: "Status",
                  // Carried-over ("paid" + paid_less_than_scheduled) reads
                  // the same as still-open "partial" — both mean "less
                  // than scheduled was ever collected on this row".
                  render: (r: any) => (
                    <StatusBadge status={r.status === "paid" && r.paid_less_than_scheduled ? "partial" : r.status} />
                  ),
                },
              ]}
              totalsRow={
                totals
                  ? ["", "Totals", money(totals.total_principal), money(totals.total_interest), money(totals.total_payable), "", ""]
                  : undefined
              }
              // Phone pass: a wide 7-column table is unreadable at 360-412px
              // even scrolled inside its own card — one stacked card per
              // instalment instead (due date, payment, balance after,
              // status), named explicitly as the highest-risk screen.
              mobileCard={(r: any) => (
                <div className="flex items-start justify-between gap-3 text-sm">
                  <div className="min-w-0">
                    <p className="font-medium">
                      #{fmtNumber(r.number)} · {r.due_date}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Principal {money(r.principal_portion)} · Interest {money(r.interest_portion)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">Balance after {money(r.balance_after)}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="font-semibold tabular-nums">{money(r.expected_amount)}</p>
                    <div className="mt-1">
                      <StatusBadge status={r.status === "paid" && r.paid_less_than_scheduled ? "partial" : r.status} />
                    </div>
                  </div>
                </div>
              )}
            />
            {schedule
              .filter((r: any) => r.status === "partial" || (r.status === "paid" && r.paid_less_than_scheduled))
              .map((r: any) => (
                <p key={r.number} className="mt-2 text-xs text-muted-foreground">
                  Instalment #{r.number}: paid {money(r.paid_interest + r.paid_principal)} of{" "}
                  {money(r.original_expected_amount)} (interest {money(r.paid_interest)}, principal{" "}
                  {money(r.paid_principal)}).{" "}
                  {r.status === "partial"
                    ? `Remaining ${money(r.expected_amount)} due by ${r.due_date}. If unpaid, the balance carries over and the schedule is recalculated.`
                    : "The remaining amount was not paid by the due date — the balance was carried over and the schedule recalculated."}
                </p>
              ))}
          </Card>

          <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
            <Card title="Repayment history">
              <DataTable
                rows={loan.repayments || []}
                empty="No repayments recorded yet."
                columns={[
                  { key: "id", label: "Receipt" },
                  { key: "payment_date", label: "Date" },
                  { key: "amount_paid", label: "Amount paid", render: (r: any) => money(r.amount_paid) },
                  { key: "interest_portion", label: "Interest", render: (r: any) => money(r.interest_portion) },
                  { key: "principal_portion", label: "Principal", render: (r: any) => money(r.principal_portion) },
                  { key: "balance_after", label: "Balance after", render: (r: any) => money(r.balance_after) },
                ]}
              />
            </Card>

            {canRecordRepayment ? (
              <Card title="Record repayment" description="Entered directly against this loan.">
                <RepaymentForm loan={loan} onRecorded={onRepaymentRecorded} />
              </Card>
            ) : hasPermission(user, "repayments:record") && loan.status !== "closed" ? (
              <Card title="Record repayment">
                <p className="text-sm text-muted-foreground">
                  {loan.status === "pending_approval"
                    ? "Repayments can be recorded once this loan has been approved."
                    : "Repayments cannot be recorded on this loan."}
                </p>
              </Card>
            ) : null}
          </div>

          {(loan.penalties || []).length ? (
            <Card title="Penalties on this loan">
              <DataTable
                rows={loan.penalties}
                columns={[
                  { key: "id", label: "Ref" },
                  { key: "amount", label: "Amount", render: (r: any) => money(r.amount) },
                  { key: "reason", label: "Reason" },
                  { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} reason={r.rejection_reason} /> },
                ]}
              />
            </Card>
          ) : null}
        </div>
      )}
    </>
  );
}
