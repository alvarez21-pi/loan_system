import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import {
  Button,
  Card,
  DataTable,
  Field,
  Input,
  InlineNote,
  ListStatus,
  PageHeader,
  Pagination,
  Select,
  SearchInput,
  StatusBadge,
  scrollToFirstError,
} from "../components/lms-ui";
import usePaginatedResource from "../hooks/usePaginatedResource.js";
import { borrowers, errorMessage, getUser, hasPermission } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/borrowers/")({
  head: () => ({
    meta: [
      { title: "Borrowers — Microfinance LMS" },
      { name: "description", content: "Register borrowers and review their contact, identity and address records." },
      { property: "og:title", content: "Borrowers — Microfinance LMS" },
      { property: "og:description", content: "Borrower register with add-borrower form and detail view." },
    ],
  }),
  component: () => (
    <AppShell>
      <BorrowersPage />
    </AppShell>
  ),
});

export const ID_TYPES: { value: string; label: string }[] = [
  { value: "nida", label: "NIDA (national ID)" },
  { value: "driving_licence", label: "Driving licence" },
  { value: "voter_id", label: "Voter ID" },
  { value: "passport", label: "Passport" },
  { value: "other", label: "Other" },
];

const EMPTY = { name: "", phone: "", id_type: "nida", id_number: "", address: "" };
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
// A photo or an ID document scan — the latter is very often a PDF, not a
// photo (Part 3.1).
const UPLOAD_TYPES = ["image/jpeg", "image/png", "image/webp", "application/pdf"];
const UPLOAD_ACCEPT = "image/jpeg,image/png,image/webp,application/pdf";

function BorrowersPage() {
  const user = getUser();
  const navigate = useNavigate();
  const canCreate = hasPermission(user, "borrowers:manage");
  const list = usePaginatedResource((params: any) => borrowers.list(params) as Promise<{ data: any[]; pagination: any }>, []);
  const [form, setForm] = useState(EMPTY);
  const [photo, setPhoto] = useState<File | null>(null);
  const [idDocument, setIdDocument] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0); // remounts the file inputs to clear them
  const [errors, setErrors] = useState<Record<string, string>>({});
  // Kept as inline state (not a toast) only for the one case that carries a
  // persistent clickable action — the duplicate-ID link to the existing
  // borrower's record below; every other result of this form is a toast.
  const [duplicate, setDuplicate] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  function set(key: string, value: string) {
    setForm({ ...form, [key]: value });
  }

  function validate() {
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "Full name is required.";
    if (!form.phone.trim()) next.phone = "Phone number is required.";
    else if (!/^\+?\d{7,15}$/.test(form.phone.replace(/\s/g, ""))) next.phone = "Enter 7–15 digits.";
    if (!form.id_number.trim()) next.id_number = "ID number is required.";
    if (!form.address.trim()) next.address = "Address is required.";
    for (const [key, file] of [["photo", photo], ["id_document", idDocument]] as const) {
      if (!file) continue;
      if (!UPLOAD_TYPES.includes(file.type)) next[key] = "Choose a JPEG, PNG, WebP image, or PDF.";
      else if (file.size > MAX_IMAGE_BYTES) next[key] = "The file must be 5 MB or smaller.";
    }
    setErrors(next);
    if (Object.keys(next).length > 0) {
      // Part 6.3: every error is a floating toast (never only visible
      // off-screen above a long form), and the first invalid field is
      // scrolled into view and briefly highlighted.
      showToast(Object.values(next)[0], "danger");
      scrollToFirstError(next);
    }
    return Object.keys(next).length === 0;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setDuplicate(null);
    if (!validate()) return;
    setBusy(true);
    try {
      const result: any = await borrowers.create(form, { photo: photo || undefined, id_document: idDocument || undefined });
      setForm(EMPTY);
      setPhoto(null);
      setIdDocument(null);
      setFileKey((n) => n + 1);
      showToast(result?.warning ? `Borrower saved. ${result.warning}` : "Borrower saved.", "success");
      list.reload();
    } catch (error: any) {
      // A duplicate ID (409) carries a link to the existing borrower instead
      // of a plain message (Part 3.3) — kept inline since a toast can't hold
      // a clickable action; every other failure is a toast only.
      if (error?.payload?.existing_borrower_id) {
        setDuplicate(error.payload);
        showToast(error.payload.message, "danger");
      } else {
        showToast(errorMessage(error), "danger");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Borrowers" description="Customer register for all loan applications." />

      <div className={`grid gap-4 ${canCreate ? "xl:grid-cols-[1.6fr_1fr]" : ""}`}>
        <Card
          title="Borrower list"
          description={`${list.pagination ? list.pagination.total : (list.data || []).length} records`}
          actions={<SearchInput value={list.q} onChange={list.setQ} placeholder="Search by name or phone" />}
        >
          <ListStatus loading={list.loading} error={list.error} empty={!list.loading && !list.error && (list.data || []).length === 0} emptyMessage="No borrowers yet." />
          {!list.loading && !list.error && (list.data || []).length > 0 ? (
            <DataTable
              rows={list.data || []}
              onRowClick={(r: any) => navigate({ to: "/borrowers/$id", params: { id: String(r.id) } })}
              sort={list.sort}
              order={list.order}
              onSort={list.toggleSort}
              columns={[
                { key: "name", label: "Name", sortKey: "name" },
                { key: "phone", label: "Phone", sortKey: "phone" },
                {
                  key: "id_number",
                  label: "ID",
                  render: (r: any) => (
                    <span>
                      {r.id_number} <span className="text-xs text-muted-foreground">({ID_TYPES.find((t) => t.value === r.id_type)?.label || r.id_type})</span>
                    </span>
                  ),
                },
                // Part 6.2: no ID-verification column at all while no provider
                // is configured — never a column full of "not configured".
                ...((list.data || []).some((r: any) => r.id_verification_configured)
                  ? [
                      {
                        key: "id_verified",
                        label: "ID Verification",
                        // Never "pending"/"approved" here — that vocabulary means
                        // maker-checker elsewhere in the app, and borrowers have no
                        // approval step at all (Part 2).
                        render: (r: any) => <StatusBadge status={r.id_verified ? "verified" : "unverified"} />,
                      },
                    ]
                  : []),
                { key: "address", label: "Address" },
                {
                  key: "actions",
                  label: "",
                  render: (r: any) => (
                    <Link to="/borrowers/$id" params={{ id: String(r.id) }} className="lms-btn lms-btn-outline" onClick={(e) => e.stopPropagation()}>
                      View
                    </Link>
                  ),
                },
              ]}
              // Phone pass: name + ID up top, phone/address below — tapping
              // the card opens the borrower the same as a row click.
              mobileCard={(r: any) => (
                <div>
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 truncate font-medium">{r.name}</p>
                    {r.id_verification_configured ? <StatusBadge status={r.id_verified ? "verified" : "unverified"} /> : null}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {r.phone} · {r.id_number}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">{r.address}</p>
                </div>
              )}
            />
          ) : null}
          <Pagination page={list.page} pagination={list.pagination} onPageChange={list.setPage} />
        </Card>

        {canCreate ? (
          <Card title="Add borrower">
            <form onSubmit={onSubmit} className="space-y-3" noValidate>
              {duplicate ? (
                <InlineNote tone="danger">
                  {duplicate.message}{" "}
                  <Link to="/borrowers/$id" params={{ id: String(duplicate.existing_borrower_id) }} className="underline">
                    View {duplicate.existing_borrower_name}'s record
                  </Link>
                </InlineNote>
              ) : null}
              <Field label="Full name" name="name" error={errors.name}>
                <Input value={form.name} aria-invalid={Boolean(errors.name)} onChange={(e: any) => set("name", e.target.value)} />
              </Field>
              <Field label="Phone" name="phone" error={errors.phone}>
                <Input value={form.phone} aria-invalid={Boolean(errors.phone)} onChange={(e: any) => set("phone", e.target.value)} />
              </Field>
              <Field label="ID type">
                <Select value={form.id_type} onChange={(e) => set("id_type", e.target.value)}>
                  {ID_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field
                label="ID number"
                name="id_number"
                error={errors.id_number}
                hint={form.id_type === "nida" ? "Typically 20 digits." : undefined}
              >
                <Input value={form.id_number} aria-invalid={Boolean(errors.id_number)} onChange={(e: any) => set("id_number", e.target.value)} />
              </Field>
              <Field label="Address" name="address" error={errors.address}>
                <Input value={form.address} aria-invalid={Boolean(errors.address)} onChange={(e: any) => set("address", e.target.value)} />
              </Field>
              <Field label="Profile photo" name="photo" error={errors.photo} hint="Optional — up to 5 MB.">
                <input key={`photo-${fileKey}`} type="file" accept={UPLOAD_ACCEPT} className="lms-input" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
              </Field>
              <Field label="ID document" name="id_document" error={errors.id_document} hint="Optional — photo, scan, or PDF.">
                <input key={`id-${fileKey}`} type="file" accept={UPLOAD_ACCEPT} className="lms-input" onChange={(e) => setIdDocument(e.target.files?.[0] ?? null)} />
              </Field>
              <Button type="submit" disabled={busy} className="w-full">
                {busy ? "Saving…" : "Save borrower"}
              </Button>
            </form>
          </Card>
        ) : null}
      </div>
    </>
  );
}
