import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, Notice, PageHeader } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { borrowers, errorMessage } from "../lib/api";

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

const EMPTY = { name: "", phone: "", id_number: "", address: "", photo_url: "" };

function BorrowersPage() {
  const list = useResource(() => borrowers.list(), []);
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
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
    if (form.photo_url && !/^https?:\/\//i.test(form.photo_url)) next.photo_url = "Must start with http:// or https://";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setMessage("");
    setFailure("");
    if (!validate()) return;
    setBusy(true);
    try {
      await borrowers.create(form);
      setForm(EMPTY);
      setMessage("Borrower saved.");
      list.reload();
    } catch (error) {
      setFailure(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Borrowers" description="Customer register for all loan applications." />
      <Notice tone="danger">{list.error}</Notice>

      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card title="Borrower list" description={`${(list.data || []).length} records`}>
          <DataTable
            rows={list.data || []}
            empty={list.loading ? "Loading…" : "No borrowers yet."}
            columns={[
              { key: "name", label: "Name" },
              { key: "phone", label: "Phone" },
              { key: "id_number", label: "ID number" },
              { key: "address", label: "Address" },
              {
                key: "actions",
                label: "",
                render: (r: any) => (
                  <Link to="/borrowers/$id" params={{ id: String(r.id) }} className="lms-btn lms-btn-outline">
                    View
                  </Link>
                ),
              },
            ]}
          />
        </Card>

        <Card title="Add borrower">
          <form onSubmit={onSubmit} className="space-y-3" noValidate>
            <Notice tone="success">{message}</Notice>
            <Notice tone="danger">{failure}</Notice>
            <Field label="Full name" error={errors.name}>
              <Input value={form.name} aria-invalid={Boolean(errors.name)} onChange={(e: any) => set("name", e.target.value)} />
            </Field>
            <Field label="Phone" error={errors.phone}>
              <Input value={form.phone} aria-invalid={Boolean(errors.phone)} onChange={(e: any) => set("phone", e.target.value)} />
            </Field>
            <Field label="ID number" error={errors.id_number}>
              <Input value={form.id_number} aria-invalid={Boolean(errors.id_number)} onChange={(e: any) => set("id_number", e.target.value)} />
            </Field>
            <Field label="Address" error={errors.address}>
              <Input value={form.address} aria-invalid={Boolean(errors.address)} onChange={(e: any) => set("address", e.target.value)} />
            </Field>
            <Field label="Photo URL" error={errors.photo_url} hint="Optional">
              <Input value={form.photo_url} aria-invalid={Boolean(errors.photo_url)} onChange={(e: any) => set("photo_url", e.target.value)} />
            </Field>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Saving…" : "Save borrower"}
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}
