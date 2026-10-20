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
  Modal,
  PageHeader,
  Pagination,
  Select,
  SearchInput,
  StatusBadge,
  TextLink,
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
  const canReactivate = user?.role === "ceo" || user?.role === "head_manager";
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

  // The edit form writes directly — no approval step for a borrower edit.
  // editForm holds the in-progress field values; editTarget is the
  // borrower being edited.
  const [editTarget, setEditTarget] = useState<any>(null);
  const [editForm, setEditForm] = useState<any>(null);
  const [editBusy, setEditBusy] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [deleteReason, setDeleteReason] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);

  function set(key: string, value: string) {
    setForm({ ...form, [key]: value });
  }

  function openEdit(row: any) {
    setEditTarget(row);
    setEditForm({ name: row.name, phone: row.phone, id_type: row.id_type || "nida", id_number: row.id_number || "", email: row.email || "", address: row.address || "" });
  }

  async function submitEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editTarget || !editForm) return;
    setEditBusy(true);
    try {
      const result: any = await borrowers.update(editTarget.id, editForm);
      if (result?.message === "No changes to apply.") {
        showToast("No changes to apply.", "info");
      } else {
        showToast("Borrower updated.", "success");
        if (result?.duplicate_warning) {
          setDuplicate(result.duplicate_warning);
          showToast(result.duplicate_warning.message, "warning");
        }
      }
      setEditTarget(null);
      setEditForm(null);
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setEditBusy(false);
    }
  }

  function openDelete(row: any) {
    setDeleteTarget(row);
    setDeleteReason("");
  }

  async function submitDelete() {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      await borrowers.proposeDelete(deleteTarget.id, deleteReason || undefined);
      showToast(
        deleteTarget.has_loan_history
          ? "Deactivation proposed — it will apply once a Checker approves it."
          : "Deletion proposed — it will apply once a Checker approves it.",
        "success",
      );
      setDeleteTarget(null);
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setDeleteBusy(false);
    }
  }

  async function reactivate(row: any) {
    if (!window.confirm(`Reactivate ${row.name}? They will reappear in new-loan selection.`)) return;
    try {
      await borrowers.reactivate(row.id);
      showToast(`${row.name} reactivated.`, "success");
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  function validate() {
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "Full name is required.";
    if (!form.phone.trim()) next.phone = "Phone number is required.";
    else if (!/^\+?\d{7,15}$/.test(form.phone.replace(/\s/g, ""))) next.phone = "Enter 7–15 digits.";
    // ID is optional at creation ("ID pending") — never a gate on
    // anything, including a loan; just a flag so staff can track and note why.
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
      // A same-ID/phone match is now a WARNING, never a hard block — the
      // borrower IS saved either way; this just surfaces the possible
      // coincidence with a link to each matching record (Part 3.3).
      if (result?.duplicate_warning) {
        setDuplicate(result.duplicate_warning);
        showToast(`Borrower saved. ${result.duplicate_warning.message}`, "warning");
      } else {
        showToast(result?.warning ? `Borrower saved. ${result.warning}` : "Borrower saved.", "success");
      }
      list.reload();
    } catch (error: any) {
      // An EXACT ID-number collision still hard-blocks at the database
      // (two people can never genuinely share one national ID) — a
      // different, 409 path from the soft duplicate_warning above.
      if (error?.payload?.existing_borrower_id) {
        setDuplicate({ message: error.payload.message, matches: [{ id: error.payload.existing_borrower_id, name: error.payload.existing_borrower_name }] });
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
                {
                  key: "name",
                  label: "Name",
                  sortKey: "name",
                  render: (r: any) => (
                    <span className={r.is_active === false ? "text-muted-foreground" : ""}>
                      {r.name}
                      {r.is_active === false ? <span className="ml-2 lms-badge lms-badge-danger">Inactive</span> : null}
                    </span>
                  ),
                },
                { key: "phone", label: "Phone", sortKey: "phone" },
                {
                  key: "id_number",
                  label: "ID",
                  render: (r: any) =>
                    r.id_pending ? (
                      <span className="lms-badge lms-badge-warning">ID pending</span>
                    ) : (
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
                        render: (r: any) => (r.id_pending ? "—" : <StatusBadge status={r.id_verified ? "verified" : "unverified"} />),
                      },
                    ]
                  : []),
                { key: "address", label: "Address" },
                {
                  key: "actions",
                  label: "",
                  render: (r: any) => (
                    <div className="flex flex-wrap items-center gap-2" onClick={(e) => e.stopPropagation()}>
                      <Link to="/borrowers/$id" params={{ id: String(r.id) }} className="lms-btn lms-btn-outline">
                        View
                      </Link>
                      {canCreate && r.is_active !== false ? (
                        <>
                          <TextLink
                            disabled={Boolean(r.pending_request)}
                            onClick={() => openEdit(r)}
                          >
                            Edit
                          </TextLink>
                          <TextLink tone="danger" disabled={Boolean(r.pending_request)} onClick={() => openDelete(r)}>
                            Delete
                          </TextLink>
                        </>
                      ) : null}
                      {canReactivate && r.is_active === false ? (
                        <TextLink onClick={() => reactivate(r)}>Reactivate</TextLink>
                      ) : null}
                      {r.pending_request ? (
                        <span className="text-xs text-muted-foreground">
                          {r.pending_request.action === "edit" ? "Edit" : r.pending_request.action === "deactivate" ? "Deactivation" : "Deletion"} pending
                        </span>
                      ) : null}
                    </div>
                  ),
                },
              ]}
              // Phone pass: name + ID up top, phone/address below — tapping
              // the card opens the borrower the same as a row click.
              mobileCard={(r: any) => (
                <div>
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 truncate font-medium">
                      {r.name}
                      {r.is_active === false ? <span className="ml-2 lms-badge lms-badge-danger">Inactive</span> : null}
                    </p>
                    {r.id_pending ? (
                      <span className="lms-badge lms-badge-warning">ID pending</span>
                    ) : r.id_verification_configured ? (
                      <StatusBadge status={r.id_verified ? "verified" : "unverified"} />
                    ) : null}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {r.phone} · {r.id_pending ? "No ID on file" : r.id_number}
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
                <InlineNote tone="warning">
                  {duplicate.message}{" "}
                  {(duplicate.matches || []).map((m: any, i: number) => (
                    <span key={m.id}>
                      {i > 0 ? ", " : ""}
                      <Link to="/borrowers/$id" params={{ id: String(m.id) }} className="underline">
                        View {m.name}'s record
                      </Link>
                    </span>
                  ))}
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
                label="ID number (optional)"
                name="id_number"
                error={errors.id_number}
                hint={
                  form.id_type === "nida"
                    ? "Typically 20 digits. Leave blank if not submitted yet — doesn't stop a loan being issued."
                    : "Leave blank if not submitted yet — doesn't stop a loan being issued."
                }
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

      {editTarget && editForm ? (
        <Modal title={`Edit — ${editTarget.name}`} description="Applies immediately." onClose={() => setEditTarget(null)} size="sm">
          <form onSubmit={submitEdit} className="space-y-3" noValidate>
            <Field label="Full name">
              <Input value={editForm.name} onChange={(e: any) => setEditForm({ ...editForm, name: e.target.value })} />
            </Field>
            <Field label="Phone">
              <Input value={editForm.phone} onChange={(e: any) => setEditForm({ ...editForm, phone: e.target.value })} />
            </Field>
            <Field label="ID type">
              <Select value={editForm.id_type} onChange={(e: any) => setEditForm({ ...editForm, id_type: e.target.value })}>
                {ID_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </Select>
            </Field>
            <Field label="ID number" hint="Leave blank for ID pending.">
              <Input value={editForm.id_number} onChange={(e: any) => setEditForm({ ...editForm, id_number: e.target.value })} />
            </Field>
            <Field label="Email">
              <Input value={editForm.email} onChange={(e: any) => setEditForm({ ...editForm, email: e.target.value })} />
            </Field>
            <Field label="Address">
              <Input value={editForm.address} onChange={(e: any) => setEditForm({ ...editForm, address: e.target.value })} />
            </Field>
            <div className="flex gap-2 pt-1">
              <Button type="submit" disabled={editBusy} className="flex-1">{editBusy ? "Saving…" : "Save"}</Button>
              <Button type="button" variant="outline" onClick={() => setEditTarget(null)}>Cancel</Button>
            </div>
          </form>
        </Modal>
      ) : null}

      {deleteTarget ? (
        <Modal title={`Delete — ${deleteTarget.name}`} onClose={() => setDeleteTarget(null)} size="sm">
          <div className="space-y-3">
            <InlineNote tone={deleteTarget.has_loan_history ? "warning" : "danger"}>
              {deleteTarget.has_loan_history
                ? "This borrower has loan history, so this will DEACTIVATE them (soft delete) — they stay correct in their existing loan records but disappear from new-loan selection. This can be reversed later."
                : "This borrower has no loan history, so this will be a PERMANENT deletion once approved — it cannot be undone."}
              {" "}This proposal still needs a Checker's approval, same as an edit.
            </InlineNote>
            <Field label="Reason (optional)">
              <Input value={deleteReason} onChange={(e: any) => setDeleteReason(e.target.value)} />
            </Field>
            <div className="flex gap-2 pt-1">
              <Button variant="danger" disabled={deleteBusy} onClick={submitDelete} className="flex-1">
                {deleteBusy ? "Proposing…" : deleteTarget.has_loan_history ? "Propose deactivation" : "Propose deletion"}
              </Button>
              <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            </div>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
