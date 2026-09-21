import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, Notice, PageHeader, Select, StatusBadge, money } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { errorMessage, getUser, penalties } from "../lib/api";

export const Route = createFileRoute("/penalties")({ component: PenaltiesPage });
function PenaltiesPage() {
  const [filters, setFilters] = useState({ status: "", loan_id: "" }); const list = useResource(() => penalties.list(filters), [filters.status, filters.loan_id]); const user = getUser();
  const [form, setForm] = useState({ loan_id: "", amount: "", reason: "" }); const [message, setMessage] = useState(""); const [failure, setFailure] = useState("");
  async function reload() { list.reload(); }
  async function create(event: React.FormEvent) { event.preventDefault(); setFailure(""); try { await penalties.create({ ...form, amount: Number(form.amount), loan_id: Number(form.loan_id) }); setForm({ loan_id: "", amount: "", reason: "" }); setMessage("Penalty submitted for approval."); reload(); } catch (error) { setFailure(errorMessage(error)); } }
  async function decide(id: number, action: "approve" | "reject") { try { await penalties[action](id); reload(); } catch (error) { setFailure(errorMessage(error)); } }
  const rows = list.data || [];
  return <AppShell><PageHeader title="Penalties" description="Submit and review loan penalties." /><Notice tone="success">{message}</Notice><Notice tone="danger">{failure || list.error}</Notice>
    <div className="grid gap-4 xl:grid-cols-[1.7fr_1fr]"><Card title="Penalty register"><div className="mb-4 grid gap-2 sm:grid-cols-2"><Select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">All statuses</option><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option></Select><Input placeholder="Loan ID" value={filters.loan_id} onChange={(e) => setFilters({ ...filters, loan_id: e.target.value })} /></div><DataTable rows={rows} empty={list.loading ? "Loading..." : "No penalties."} columns={[{ key: "id", label: "Ref" }, { key: "loan_id", label: "Loan" }, { key: "amount", label: "Amount", render: (r: any) => money(r.amount) }, { key: "reason", label: "Reason" }, { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> }, { key: "actions", label: "", render: (r: any) => <div className="flex gap-2"><Button disabled={r.added_by === user?.id || r.created_by === user?.id} onClick={() => decide(r.id, "approve")}>Approve</Button><Button variant="outline" disabled={r.added_by === user?.id || r.created_by === user?.id} onClick={() => decide(r.id, "reject")}>Reject</Button></div> }]} /></Card>
      <Card title="Add penalty"><form className="space-y-3" onSubmit={create}><Field label="Loan ID"><Input type="number" required value={form.loan_id} onChange={(e) => setForm({ ...form, loan_id: e.target.value })} /></Field><Field label="Amount"><Input type="number" step="0.01" required value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></Field><Field label="Reason"><Input required value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field><Button type="submit" className="w-full">Submit penalty</Button></form></Card></div></AppShell>;
}
