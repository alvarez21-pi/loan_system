import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import {
  Button,
  Card,
  DataTable,
  Field,
  Input,
  InlineNote,
  ListStatus,
  MoneyInput,
  NumberInput,
  PageHeader,
  Pagination,
  Select,
  SearchInput,
  StatusBadge,
  fmtNumber,
  money,
  percent,
  scrollToFirstError,
} from "../components/lms-ui";
import useAutoRefresh from "../hooks/useAutoRefresh.js";
import usePaginatedResource from "../hooks/usePaginatedResource.js";
import useResource from "../hooks/useResource.js";
import { borrowers, calculator, errorMessage, getUser, hasPermission, loanProducts, loans } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/loans/")({
  head: () => ({
    meta: [
      { title: "Loans — Microfinance LMS" },
      { name: "description", content: "Create loans, track principal, interest, term and status from draft to closed." },
      { property: "og:title", content: "Loans — Microfinance LMS" },
      { property: "og:description", content: "Loan book with creation form and status tracking." },
    ],
  }),
  component: () => (
    <AppShell>
      <LoansPage />
    </AppShell>
  ),
});

const EMPTY = {
  borrower_id: "",
  loan_product_id: "",
  principal_amount: "",
  interest_rate: "",
  term_months: "",
  start_date: "",
};

const PENDING = /pending|submitted|awaiting|review/i;
const isPending = (row: any) => PENDING.test(String(row.status || ""));

function LoansPage() {
  const user = getUser();
  const navigate = useNavigate();
  const canCreate = hasPermission(user, "loans:create");
  const canApprove = hasPermission(user, "loans:approve");

  // Two separate loads of the same endpoint, deliberately: the approval
  // queue below needs EVERY loan this user can decide on on screen at once
  // (never just the current page), while the main loan list is the
  // server-paginated/searchable one (Phase 5).
  const pendingList = useResource(() => loans.list(), []);
  const list = usePaginatedResource((params: any) => loans.list(params) as Promise<{ data: any[]; pagination: any }>, []);
  const borrowerList = useResource(() => borrowers.list(), []);
  const productList = useResource(() => loanProducts.list(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [busyKey, setBusyKey] = useState("");

  const [preview, setPreview] = useState<any>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState("");

  useAutoRefresh(pendingList.reload);
  useAutoRefresh(list.reload);

  // No product selected -> "Negotiated rate": the Maker sets principal/
  // rate/term directly (Part 2.2). A product selected -> only its RATE is
  // locked (Part 2.1) — the TERM IS NEVER LOCKED, always entered per loan,
  // same as a negotiated-rate loan; the product's own optional min/max term
  // apply only as validation bounds. Enforced again server-side regardless
  // of what this form sends.
  const selectedProduct: any = (productList.data || []).find((p: any) => String(p.id) === String(form.loan_product_id));
  const rateLocked = Boolean(selectedProduct);

  function set(key: string, value: string) {
    const next = { ...form, [key]: value };
    if (key === "loan_product_id") {
      const product: any = (productList.data || []).find((p: any) => String(p.id) === value);
      next.interest_rate = product ? String(product.default_interest_rate ?? "") : "";
      // Term is never touched here — it stays whatever the Maker already entered.
    }
    setForm(next);
  }

  // Loan creation is one flow, not two: the schedule preview lives inside
  // this same form and updates live as principal/rate/term/start date
  // change, debounced against the same calculator endpoint the loan itself
  // is persisted with — due dates included (Part 3), same preview either way.
  useEffect(() => {
    const principal = Number(form.principal_amount);
    const rate = form.interest_rate;
    const term = Number(form.term_months);
    if (!principal || rate === "" || rate === undefined || !term) {
      setPreview(null);
      setPreviewError("");
      return;
    }
    setPreviewBusy(true);
    const handle = setTimeout(() => {
      calculator
        .preview({
          principal, interest_rate: Number(rate), term_months: term, interest_type: "reducing_balance",
          start_date: form.start_date || undefined,
        })
        .then((result) => {
          setPreview(result);
          setPreviewError("");
        })
        .catch((error) => {
          setPreview(null);
          setPreviewError(errorMessage(error));
        })
        .finally(() => setPreviewBusy(false));
    }, 400);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.principal_amount, form.interest_rate, form.term_months, form.start_date]);

  function validate() {
    const next: Record<string, string> = {};
    if (!form.borrower_id) next.borrower_id = "Select a borrower.";
    if (!Number(form.principal_amount)) next.principal_amount = "Enter the principal amount.";
    if (form.interest_rate === "" || Number(form.interest_rate) < 0) next.interest_rate = "Enter a monthly interest rate.";
    if (!Number(form.term_months)) next.term_months = "Enter the term in months.";
    if (!form.start_date) next.start_date = "Select a start date.";

    if (selectedProduct) {
      const amount = Number(form.principal_amount);
      if (selectedProduct.min_amount != null && amount < Number(selectedProduct.min_amount))
        next.principal_amount = `Minimum for this product is ${money(selectedProduct.min_amount)}.`;
      if (selectedProduct.max_amount != null && amount > Number(selectedProduct.max_amount))
        next.principal_amount = `Maximum for this product is ${money(selectedProduct.max_amount)}.`;
      const term = Number(form.term_months);
      if (selectedProduct.min_term_months != null && term < Number(selectedProduct.min_term_months))
        next.term_months = `Minimum term for this product is ${selectedProduct.min_term_months} months.`;
      if (selectedProduct.max_term_months != null && term > Number(selectedProduct.max_term_months))
        next.term_months = `Maximum term for this product is ${selectedProduct.max_term_months} months.`;
    }
    setErrors(next);
    if (Object.keys(next).length > 0) {
      // Part 6.3: toast + scroll-to-and-highlight the first invalid field.
      showToast(Object.values(next)[0], "danger");
      scrollToFirstError(next);
    }
    return Object.keys(next).length === 0;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    setBusy(true);
    try {
      const created: any = await loans.create({
        borrower_id: form.borrower_id,
        loan_product_id: form.loan_product_id,
        principal_amount: Number(form.principal_amount),
        interest_rate: Number(form.interest_rate),
        term_months: Number(form.term_months),
        start_date: form.start_date,
      });
      setForm(EMPTY);
      setPreview(null);
      const newId = created?.loan?.id;
      showToast(
        "Loan created and sent for approval. Its schedule is visible on the loan's own page right away.",
        "success",
        newId ? { link: { label: `Open Loan #${newId}`, to: `/loans/${newId}` } } : undefined,
      );
      pendingList.reload();
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function decide(row: any, action: "approve" | "reject") {
    const borrowerName = row.borrower_name || "this borrower";
    const question =
      action === "approve"
        ? `This will activate Loan #${row.id} for ${borrowerName} — ${money(row.principal_amount)} at ${percent(row.interest_rate)} per month over ${fmtNumber(row.term_months)} months, and deliver the schedule to the borrower. Approve?`
        : `This will reject Loan #${row.id} for ${borrowerName}. Are you sure?`;
    if (!window.confirm(question)) return;
    let rejection_reason: string | undefined;
    if (action === "reject") {
      rejection_reason = window.prompt("Reason for rejection:") || undefined;
      if (!rejection_reason) return;
    }
    setBusyKey(`${row.id}-${action}`);
    try {
      await loans[action](row.id, action === "reject" ? { rejection_reason } : undefined);
      showToast(`Loan #${row.id} ${action === "approve" ? "approved" : "rejected"}.`, "success");
      pendingList.reload();
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusyKey("");
    }
  }

  const rows = list.data || [];
  // The backend decides who may act on each row (not the creator, and in scope).
  const pendingRows = (pendingList.data || []).filter((r: any) => isPending(r) && r.can_decide);

  return (
    <>
      <PageHeader title="Loans" description="Loan book and new loan applications." />
      <InlineNote tone="danger">{pendingList.error}</InlineNote>

      {canApprove ? (
        <Card title="Pending my approval" description={`${fmtNumber(pendingRows.length)} loans`} className="mb-4">
          <DataTable
            rows={pendingRows}
            empty="No loans waiting for your approval."
            columns={[
              { key: "id", label: "Loan" },
              { key: "borrower_name", label: "Borrower", render: (r: any) => r.borrower_name || r.borrower?.name || "—" },
              { key: "principal_amount", label: "Principal", render: (r: any) => money(r.principal_amount) },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} reason={r.rejection_reason} /> },
              {
                key: "actions",
                label: "",
                render: (r: any) => (
                  <div className="flex gap-2">
                    <Button disabled={busyKey === `${r.id}-approve`} onClick={() => decide(r, "approve")}>
                      Approve
                    </Button>
                    <Button variant="outline" disabled={busyKey === `${r.id}-reject`} onClick={() => decide(r, "reject")}>
                      Reject
                    </Button>
                  </div>
                ),
              },
            ]}
          />
        </Card>
      ) : null}

      <div className={`grid gap-4 ${canCreate ? "xl:grid-cols-[1.6fr_1fr]" : ""}`}>
        <Card
          title="Loan list"
          description={`${list.pagination ? list.pagination.total : rows.length} records`}
          actions={<SearchInput value={list.q} onChange={list.setQ} placeholder="Search by borrower name" />}
        >
          <ListStatus loading={list.loading} error={list.error} empty={!list.loading && !list.error && rows.length === 0} emptyMessage="No loans yet." />
          {!list.loading && !list.error && rows.length > 0 ? (
            <DataTable
              rows={rows}
              onRowClick={(r: any) => navigate({ to: "/loans/$id", params: { id: String(r.id) } })}
              sort={list.sort}
              order={list.order}
              onSort={list.toggleSort}
              columns={[
                {
                  key: "id",
                  label: "Loan",
                  sortKey: "id",
                  render: (r: any) => (
                    <Link to="/loans/$id" params={{ id: String(r.id) }} className="text-primary underline" onClick={(e) => e.stopPropagation()}>
                      #{r.id}
                    </Link>
                  ),
                },
                { key: "borrower_name", label: "Borrower", sortKey: "borrower_name", render: (r: any) => r.borrower_name || r.borrower?.name || "—" },
                { key: "product_name", label: "Product", render: (r: any) => r.product_name || r.loan_product?.name || "Negotiated rate" },
                { key: "principal_amount", label: "Principal", render: (r: any) => money(r.principal_amount) },
                { key: "interest_rate", label: "Monthly Rate (%)", render: (r: any) => percent(r.interest_rate) },
                { key: "term_months", label: "Term (months)", render: (r: any) => fmtNumber(r.term_months) },
                { key: "start_date", label: "Start", sortKey: "start_date" },
                { key: "outstanding_balance", label: "Balance", render: (r: any) => money(r.outstanding_balance) },
                {
                  key: "status",
                  label: "Status",
                  sortKey: "status",
                  render: (r: any) => <StatusBadge status={r.status} reason={r.rejection_reason} />,
                },
              ]}
              // Phone pass: a card per loan (name + amount up top, status +
              // date below) instead of a 9-column table at 360-412px.
              mobileCard={(r: any) => (
                <div>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-medium">
                        Loan #{r.id} — {r.borrower_name || r.borrower?.name || "—"}
                      </p>
                      <p className="text-xs text-muted-foreground">{r.product_name || r.loan_product?.name || "Negotiated rate"}</p>
                    </div>
                    <p className="shrink-0 font-semibold tabular-nums">{money(r.principal_amount)}</p>
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                    <StatusBadge status={r.status} reason={r.rejection_reason} />
                    <span>{r.start_date}</span>
                  </div>
                </div>
              )}
            />
          ) : null}
          <Pagination page={list.page} pagination={list.pagination} onPageChange={list.setPage} />
        </Card>

        {canCreate ? (
          <Card title="Create loan">
            <form onSubmit={onSubmit} className="space-y-3" noValidate>
              <Field label="Borrower" name="borrower_id" error={errors.borrower_id}>
                <Select value={form.borrower_id} onChange={(e: any) => set("borrower_id", e.target.value)}>
                  <option value="">Select borrower</option>
                  {(borrowerList.data || []).map((b: any) => (
                    <option key={b.id} value={b.id}>
                      {b.name} — {b.phone}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Loan product" name="loan_product_id" error={errors.loan_product_id}>
                <Select value={form.loan_product_id} onChange={(e: any) => set("loan_product_id", e.target.value)}>
                  <option value="">Negotiated rate</option>
                  {(productList.data || []).map((p: any) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Principal amount" name="principal_amount" error={errors.principal_amount}>
                <MoneyInput value={form.principal_amount} onValueChange={(v) => set("principal_amount", v)} />
              </Field>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field
                  label="Monthly Interest Rate (%)"
                  name="interest_rate"
                  error={errors.interest_rate}
                  hint={rateLocked ? "Locked to this product's rate." : undefined}
                >
                  <NumberInput
                    decimals={2}
                    value={form.interest_rate}
                    onValueChange={(v) => set("interest_rate", v)}
                    disabled={rateLocked}
                  />
                </Field>
                <Field
                  label="Term (months)"
                  name="term_months"
                  error={errors.term_months}
                  hint={
                    selectedProduct && (selectedProduct.min_term_months || selectedProduct.max_term_months)
                      ? `Between ${selectedProduct.min_term_months ?? 1} and ${selectedProduct.max_term_months ?? "∞"} months for this product.`
                      : undefined
                  }
                >
                  <NumberInput
                    integer
                    value={form.term_months}
                    onValueChange={(v) => set("term_months", v)}
                  />
                </Field>
              </div>
              <Field label="Start date" name="start_date" error={errors.start_date}>
                <Input type="date" value={form.start_date} onChange={(e: any) => set("start_date", e.target.value)} />
              </Field>

              {previewBusy || preview || previewError ? (
                <div className="rounded-md border border-border p-3">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Schedule preview
                  </p>
                  <InlineNote tone="danger">{previewError}</InlineNote>
                  {previewBusy ? <p className="text-xs text-muted-foreground">Calculating…</p> : null}
                  {preview ? (
                    <>
                      <div className="max-h-48 overflow-y-auto">
                        <DataTable
                          rows={preview.schedule || []}
                          columns={[
                            { key: "period", label: "#", render: (r: any) => fmtNumber(r.period) },
                            { key: "due_date", label: "Due date" },
                            { key: "principal_portion", label: "Principal", render: (r: any) => money(r.principal_portion) },
                            { key: "interest_portion", label: "Interest", render: (r: any) => money(r.interest_portion) },
                            { key: "payment_amount", label: "Payment", render: (r: any) => money(r.payment_amount) },
                            { key: "balance_after", label: "Balance", render: (r: any) => money(r.balance_after) },
                          ]}
                          totalsRow={
                            preview.totals
                              ? ["Totals", "", money(preview.totals.total_principal), money(preview.totals.total_interest), money(preview.totals.total_payable), ""]
                              : undefined
                          }
                        />
                      </div>
                    </>
                  ) : null}
                </div>
              ) : null}

              <Button type="submit" disabled={busy} className="w-full">
                {busy ? "Saving…" : "Create loan"}
              </Button>
            </form>
          </Card>
        ) : null}
      </div>
    </>
  );
}
