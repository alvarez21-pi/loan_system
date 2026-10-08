import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, InlineNote, MoneyInput, PageHeader, Select, money, useScrollIntoViewOnChange } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { assetTypes, assets, errorMessage, getUser, hasPermission } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/assets")({
  head: () => ({
    meta: [
      { title: "Assets — Microfinance LMS" },
      { name: "description", content: "Track branch assets, their type and current value." },
    ],
  }),
  component: () => (
    <AppShell>
      <AssetsPage />
    </AppShell>
  ),
});

const EMPTY = { name: "", asset_type_id: "", value: "", date_acquired: "", notes: "" };

function AssetsPage() {
  const user = getUser();
  const canManage = hasPermission(user, "assets:manage");
  const list = useResource(() => assets.list(), []);
  const typeList = useResource(() => assetTypes.list(), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [editing, setEditing] = useState<number | null>(null);
  const [newTypeName, setNewTypeName] = useState("");
  const formRef = useScrollIntoViewOnChange<HTMLDivElement>(editing);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      const body = { ...form, value: Number(form.value), asset_type_id: form.asset_type_id ? Number(form.asset_type_id) : undefined };
      if (editing) await assets.update(editing, body);
      else await assets.create(body);
      setForm(EMPTY);
      setEditing(null);
      showToast(editing ? "Asset updated." : "Asset created.", "success");
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  async function remove(id: number) {
    if (!window.confirm("Archive this asset?")) return;
    try {
      await assets.remove(id);
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  async function addType(e: React.FormEvent) {
    e.preventDefault();
    if (!newTypeName.trim()) return;
    try {
      await assetTypes.create(newTypeName.trim());
      setNewTypeName("");
      typeList.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  return (
    <>
      <PageHeader title="Assets" description="Branch assets by type and value." />
      <InlineNote tone="danger">{list.error}</InlineNote>
      <div className={`grid gap-4 ${canManage ? "xl:grid-cols-[1.7fr_1fr]" : ""}`}>
        <Card title="Asset register">
          <DataTable
            rows={list.data || []}
            empty={list.loading ? "Loading…" : "No assets."}
            columns={[
              { key: "name", label: "Name" },
              { key: "asset_type_name", label: "Type", render: (r: any) => r.asset_type_name || r.type },
              { key: "value", label: "Value", render: (r: any) => money(r.value) },
              { key: "date_acquired", label: "Acquired" },
              {
                key: "actions",
                label: "",
                render: (r: any) =>
                  canManage ? (
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        onClick={() => {
                          setEditing(r.id);
                          setForm({ name: r.name, asset_type_id: r.asset_type_id ?? "", value: r.value, date_acquired: r.date_acquired, notes: r.notes || "" });
                        }}
                      >
                        Edit
                      </Button>
                      <Button variant="outline" onClick={() => remove(r.id)}>
                        Archive
                      </Button>
                    </div>
                  ) : null,
              },
            ]}
          />
        </Card>
        {canManage ? (
          <div className="space-y-4">
            <div ref={formRef}>
            <Card title={editing ? "Edit asset" : "Add asset"}>
              <form className="space-y-3" onSubmit={save}>
                <Field label="Name">
                  <Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                </Field>
                <Field label="Type">
                  <Select required value={form.asset_type_id} onChange={(e) => setForm({ ...form, asset_type_id: e.target.value })}>
                    <option value="">Select type</option>
                    {(typeList.data || []).map((t: any) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Value">
                  <MoneyInput value={form.value} onValueChange={(v) => setForm({ ...form, value: v })} />
                </Field>
                <Field label="Date acquired">
                  <Input type="date" required value={form.date_acquired} onChange={(e) => setForm({ ...form, date_acquired: e.target.value })} />
                </Field>
                <Field label="Notes">
                  <Input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                </Field>
                <div className="flex gap-2">
                  <Button type="submit" className="flex-1">
                    {editing ? "Update asset" : "Save asset"}
                  </Button>
                  {editing ? (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setEditing(null);
                        setForm(EMPTY);
                      }}
                    >
                      Cancel
                    </Button>
                  ) : null}
                </div>
              </form>
            </Card>
            </div>
            <Card title="Add asset type">
              <form className="flex gap-2" onSubmit={addType}>
                <Input value={newTypeName} placeholder="e.g. Generator" onChange={(e) => setNewTypeName(e.target.value)} />
                <Button type="submit">Add</Button>
              </form>
            </Card>
          </div>
        ) : null}
      </div>
    </>
  );
}
