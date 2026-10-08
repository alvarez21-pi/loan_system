import { createFileRoute, Link } from "@tanstack/react-router";
import AppShell from "../components/AppShell";
import { useEffect, useState } from "react";
import { Button, Card, DataTable, InlineNote, PageHeader, StatusBadge, money } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { borrowers, errorMessage, getUser, hasPermission, loans } from "../lib/api";
import { showToast } from "../lib/toast";
import { ID_TYPES } from "./borrowers.index";

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

/**
 * An uploaded photo or ID document. Files sit behind authentication, so the
 * browser cannot load them with a plain <img src>: fetch with the session
 * token and show the result from a blob URL (released when it changes or the
 * page goes away). A PDF upload (Part 3.1) can't render as an <img> — shown
 * instead as an embedded viewer with an "Open in new tab" fallback link.
 */
function SecureImage({ id, kind, exists, alt, version }: { id: string; kind: "photo" | "id-document"; exists: boolean; alt: string; version: number }) {
  const [src, setSrc] = useState("");
  const [isPdf, setIsPdf] = useState(false);
  useEffect(() => {
    let url = "";
    let cancelled = false;
    setSrc("");
    if (exists) {
      borrowers
        .fileBlob(id, kind)
        .then((blob: Blob) => {
          url = URL.createObjectURL(blob);
          if (cancelled) URL.revokeObjectURL(url);
          else {
            setIsPdf(blob.type === "application/pdf");
            setSrc(url);
          }
        })
        .catch(() => undefined);
    }
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [id, kind, exists, version]);
  if (!exists) return <p className="text-sm text-muted-foreground">Not uploaded.</p>;
  if (!src) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (isPdf) {
    return (
      <div className="space-y-1">
        <embed src={src} type="application/pdf" className="h-64 w-full rounded-md border border-border" />
        <a href={src} target="_blank" rel="noopener noreferrer" className="text-xs text-primary underline">
          Open PDF in new tab
        </a>
      </div>
    );
  }
  return <img src={src} alt={alt} className="max-h-64 rounded-md border border-border object-contain" />;
}

function BorrowerDetail() {
  const { id } = Route.useParams();
  const user = getUser();
  const canUpload = hasPermission(user, "borrowers:manage");
  const detail = useResource(() => borrowers.get(id), [id]);
  const loanList = useResource(() => loans.list(), []);
  const [version, setVersion] = useState(0);
  const [verifying, setVerifying] = useState(false);
  const b: any = detail.data;

  async function upload(kind: "photo" | "id-document", file: File | undefined) {
    if (!file) return;
    try {
      await borrowers.upload(id, kind, file);
      setVersion((n) => n + 1);
      showToast(kind === "photo" ? "Profile photo uploaded." : "ID document uploaded.", "success");
      detail.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  async function verifyId() {
    setVerifying(true);
    try {
      const result: any = await borrowers.verifyId(id);
      showToast(result?.result?.message || "Verification not configured.", "info");
      detail.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setVerifying(false);
    }
  }
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
      <InlineNote tone="danger">{detail.error}</InlineNote>

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
                ["ID type", ID_TYPES.find((t) => t.value === b.id_type)?.label || b.id_type],
                ["ID number", b.id_number],
                ["Address", b.address],
                ["Registered", b.created_at],
              ].map(([label, value]) => (
                <div key={String(label)} className="flex justify-between gap-4 border-b border-border pb-2">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="text-right font-medium">{value || "—"}</dd>
                </div>
              ))}
              {/* Part 6.2: the whole verification row only ever appears once
                  a real provider is configured - never a permanent "not
                  configured" message sitting on every borrower's page. */}
              {b.id_verification_configured ? (
                <div className="flex items-center justify-between gap-4 border-b border-border pb-2">
                  <dt className="text-muted-foreground">ID verification</dt>
                  <dd className="text-right">
                    {/* Never "pending"/"approved" — borrowers have no approval
                        step (Part 2); this is only whether ID verification
                        has confirmed the number. */}
                    <StatusBadge status={b.id_verified ? "verified" : "unverified"} />
                  </dd>
                </div>
              ) : null}
            </dl>
            {canUpload && b.id_verification_configured ? (
              <div className="mt-3">
                <Button variant="outline" disabled={verifying} onClick={verifyId}>
                  {verifying ? "Checking…" : "Verify ID"}
                </Button>
              </div>
            ) : null}
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              {(
                [
                  ["photo", "Profile photo", b.has_photo],
                  ["id-document", "ID document", b.has_id_document],
                ] as const
              ).map(([kind, label, exists]) => (
                <div key={kind}>
                  <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
                  <SecureImage id={id} kind={kind} exists={Boolean(exists)} alt={`${b.name} ${label.toLowerCase()}`} version={version} />
                  {canUpload ? (
                    <label className="lms-btn lms-btn-outline mt-2 inline-block cursor-pointer">
                      {exists ? "Replace" : "Upload"}
                      <input
                        type="file"
                        accept="image/jpeg,image/png,image/webp,application/pdf"
                        className="hidden"
                        onChange={(e) => {
                          upload(kind, e.target.files?.[0]);
                          e.target.value = "";
                        }}
                      />
                    </label>
                  ) : null}
                </div>
              ))}
            </div>
          </Card>
          <Card title="Loans">
            <DataTable
              rows={theirLoans}
              empty="No loans for this borrower."
              columns={[
                {
                  key: "id",
                  label: "Loan",
                  render: (r: any) => (
                    <Link to="/loans/$id" params={{ id: String(r.id) }} className="text-primary underline">
                      #{r.id}
                    </Link>
                  ),
                },
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
