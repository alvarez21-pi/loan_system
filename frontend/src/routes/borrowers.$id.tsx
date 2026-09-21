import { createFileRoute, Link } from "@tanstack/react-router";
import AppShell from "../components/AppShell";
import { Card, DataTable, Notice, PageHeader, StatusBadge, money } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { borrowers, loans } from "../lib/api";

export const Route = createFileRoute("/borrowers/$id")({
  head: () => ({
    meta: [
      { title: "Borrower Details — Microfinance LMS" },
      { name: "description", content: "Borrower profile with identity details and linked loan history." },
      { property: "og:title", content: "Borrower Details — Microfinance LMS" },
      { property: "og:description", content: "Borrower profile and loan history." },
    ],
  }),
  component: () => (
    <AppShell>
      <BorrowerDetail />
    </AppShell>
  ),
});

function BorrowerDetail() {
  const { id } = Route.useParams();
  const detail = useResource(() => borrowers.get(id), [id]);
  const loanList = useResource(() => loans.list(), []);
  const b: any = detail.data;
  const theirLoans = (loanList.data || []).filter(
    (l: any) => String(l.borrower_id ?? l.borrower?.id) === String(id) || l.borrower_name === b?.name,
  );

  return (
    <>
      <PageHeader
        title={b?.name || "Borrower"}
        description="Borrower profile and linked loans."
        actions={
          <Link to="/borrowers" className="lms-btn lms-btn-outline">
            Back to list
          </Link>
        }
      />
      <Notice tone="danger">{detail.error}</Notice>

      {detail.loading ? (
        <Card>Loading…</Card>
      ) : !b ? (
        <Card>Borrower not found.</Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[1fr_1.4fr]">
          <Card title="Details">
            <dl className="space-y-3 text-sm">
              {[
                ["Full name", b.name],
                ["Phone", b.phone],
                ["ID number", b.id_number],
                ["Address", b.address],
                ["Registered", b.created_at],
              ].map(([label, value]) => (
                <div key={String(label)} className="flex justify-between gap-4 border-b border-border pb-2">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="text-right font-medium">{value || "—"}</dd>
                </div>
              ))}
            </dl>
            {b.photo_url ? (
              <img src={b.photo_url} alt={`${b.name} photo`} className="mt-4 h-32 w-32 rounded-md object-cover" />
            ) : null}
          </Card>
          <Card title="Loans">
            <DataTable
              rows={theirLoans}
              empty="No loans for this borrower."
              columns={[
                { key: "id", label: "Loan" },
                { key: "product_name", label: "Product" },
                { key: "principal_amount", label: "Principal", render: (r: any) => money(r.principal_amount) },
                { key: "outstanding_balance", label: "Balance", render: (r: any) => money(r.outstanding_balance) },
                { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
              ]}
            />
          </Card>
        </div>
      )}
    </>
  );
}
