import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import AppShell from "../components/AppShell";
import {
  Card,
  DataTable,
  Field,
  Input,
  Notice,
  PageHeader,
  Select,
} from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { auditLogs } from "../lib/api";

export const Route = createFileRoute("/audit-logs")({
  head: () => ({
    meta: [
      { title: "Audit Logs — Microfinance LMS" },
      { name: "description", content: "Trace every create, update, approve and reject action taken in the system." },
      { property: "og:title", content: "Audit Logs — Microfinance LMS" },
      { property: "og:description", content: "Full activity trail per user, table and record." },
    ],
  }),
  component: () => (
    <AppShell>
      <AuditLogsPage />
    </AppShell>
  ),
});

function AuditLogsPage() {
  const list = useResource(() => auditLogs.list(), []);
  const [search, setSearch] = useState("");
  const [action, setAction] = useState("");

  const rows = list.data || [];

  const actions = useMemo(
    () => Array.from(new Set(rows.map((r: any) => String(r.action || "").toUpperCase()).filter(Boolean))),
    [rows],
  );

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rows.filter((r: any) => {
      if (action && String(r.action || "").toUpperCase() !== action) return false;
      if (!term) return true;
      return JSON.stringify(r).toLowerCase().includes(term);
    });
  }, [rows, search, action]);

  return (
    <>
      <PageHeader title="Audit Logs" description="Who changed what, and when." />
      <Notice tone="danger">{list.error}</Notice>

      <Card title="Activity trail" description={`${filtered.length} of ${rows.length} entries`}>
        <div className="mb-4 grid gap-3 sm:grid-cols-[2fr_1fr]">
          <Field label="Search">
            <Input
              placeholder="User, table, record or details"
              value={search}
              onChange={(e: any) => setSearch(e.target.value)}
            />
          </Field>
          <Field label="Action">
            <Select value={action} onChange={(e: any) => setAction(e.target.value)}>
              <option value="">All actions</option>
              {actions.map((a: any) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <DataTable
          rows={filtered}
          empty={list.loading ? "Loading…" : "No audit entries found."}
          columns={[
            { key: "id", label: "ID" },
            { key: "user", label: "User", render: (r: any) => r.user || r.user_name || r.username || "—" },
            { key: "action", label: "Action" },
            { key: "table_name", label: "Table", render: (r: any) => r.table_name || r.entity || "—" },
            { key: "record_id", label: "Record" },
            { key: "timestamp", label: "When", render: (r: any) => r.timestamp || r.created_at || "—" },
            { key: "details", label: "Details" },
          ]}
        />
      </Card>
    </>
  );
}
