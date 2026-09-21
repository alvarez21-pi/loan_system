import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, Notice, PageHeader, Select, StatusBadge } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { errorMessage, getUser, users, auth } from "../lib/api";

export const Route = createFileRoute("/users")({ component: UsersPage });

function UsersPage() {
  const currentUser = getUser();
  const list = useResource(() => users.list(), []);
  const [form, setForm] = useState({ name: "", email: "", phone: "", role: "maker" });
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);

  if (currentUser?.role !== "admin") return <AppShell><Notice tone="danger">Admin role required.</Notice></AppShell>;

  async function createUser(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setMessage(""); setFailure("");
    try {
      await auth.register(form);
      setMessage(`Verification email sent to ${form.email}`);
      setForm({ name: "", email: "", phone: "", role: "maker" });
      list.reload();
    } catch (error) { setFailure(errorMessage(error)); } finally { setBusy(false); }
  }

  async function deactivate(id: number) {
    try { await users.deactivate(id); list.reload(); } catch (error) { setFailure(errorMessage(error)); }
  }

  return <AppShell><PageHeader title="User management" description="Create staff accounts and manage access." /><div className="grid gap-4 xl:grid-cols-[1fr_1.7fr]"><Card title="Create staff user"><form className="space-y-3" onSubmit={createUser}><Notice tone="success">{message}</Notice><Notice tone="danger">{failure}</Notice><Field label="Name"><Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field><Field label="Email"><Input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field><Field label="Phone"><Input required value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field><Field label="Role"><Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}><option value="maker">Maker</option><option value="checker">Checker</option></Select></Field><Button type="submit" disabled={busy} className="w-full">{busy ? "Creating..." : "Create user"}</Button></form></Card><Card title="Existing users"><Notice tone="danger">{list.error}</Notice><DataTable rows={list.data || []} empty={list.loading ? "Loading..." : "No users."} columns={[{ key: "name", label: "Name" }, { key: "email", label: "Email" }, { key: "role", label: "Role" }, { key: "email_verified", label: "Verified", render: (r: any) => <StatusBadge status={r.email_verified ? "approved" : "pending"} /> }, { key: "is_active", label: "Active", render: (r: any) => <StatusBadge status={r.is_active ? "active" : "rejected"} /> }, { key: "actions", label: "", render: (r: any) => r.is_active && r.id !== currentUser.id ? <Button variant="outline" onClick={() => deactivate(r.id)}>Deactivate</Button> : null }]} /></Card></div></AppShell>;
}
