import { createFileRoute } from "@tanstack/react-router";
import AppShell from "../components/AppShell";
import {
  Card,
  DataTable,
  Field,
  InlineNote,
  ListStatus,
  PageHeader,
  Pagination,
  Select,
  SearchInput,
} from "../components/lms-ui";
import usePaginatedResource from "../hooks/usePaginatedResource.js";
import useResource from "../hooks/useResource.js";
import { auditLogs, getUser, isAdmin } from "../lib/api";
import { useState } from "react";

export const Route = createFileRoute("/audit-logs")({
  head: () => ({
    meta: [
      { title: "Audit Logs — Microfinance LMS" },
      {
        name: "description",
        content: "Trace every create, update, approve and reject action taken in the system.",
      },
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
  // CEO and manager have the full trail; checker and maker have no access to it.
  const allowed = isAdmin(getUser());
  const [action, setAction] = useState("");
  // The action dropdown's own options come from the WHOLE table (Phase 5),
  // never just the current page, so they don't change as you page through.
  const actionsList = useResource(
    () => (allowed ? auditLogs.listActions() : Promise.resolve({ data: [] })),
    [allowed],
  );
  const list = usePaginatedResource(
    (params: any) =>
      (allowed
        ? auditLogs.list({ ...params, action: action || undefined })
        : Promise.resolve({ data: [], pagination: null })) as Promise<{
        data: any[];
        pagination: any;
      }>,
    [allowed, action],
  );
  const rows = list.data || [];

  if (!allowed) return <InlineNote tone="danger">You don't have permission to do this.</InlineNote>;

  return (
    <>
      <PageHeader title="Audit Logs" description="Who changed what, and when." />

      <Card
        title="Activity trail"
        description={`${list.pagination ? list.pagination.total : rows.length} entries`}
        actions={
          <SearchInput value={list.q} onChange={list.setQ} placeholder="User, table or action" />
        }
      >
        <div className="mb-4 grid gap-3 sm:grid-cols-[1fr]">
          <Field label="Action">
            <Select value={action} onChange={(e: any) => setAction(e.target.value)}>
              <option value="">All actions</option>
              {(actionsList.data || []).map((a: any) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <ListStatus
          loading={list.loading}
          error={list.error}
          empty={!list.loading && !list.error && rows.length === 0}
          emptyMessage="No audit entries found."
        />
        {!list.loading && !list.error && rows.length > 0 ? (
          <DataTable
            rows={rows}
            sort={list.sort}
            order={list.order}
            onSort={list.toggleSort}
            columns={[
              { key: "id", label: "ID" },
              {
                key: "user",
                label: "User",
                render: (r: any) => r.user || r.user_name || r.username || "—",
              },
              { key: "action", label: "Action", sortKey: "action" },
              {
                key: "table_name",
                label: "Table",
                sortKey: "table_name",
                render: (r: any) => r.table_name || r.entity || "—",
              },
              { key: "record_id", label: "Record" },
              {
                key: "timestamp",
                label: "When",
                sortKey: "timestamp",
                render: (r: any) => r.timestamp || r.created_at || "—",
              },
              { key: "details", label: "Details" },
            ]}
          />
        ) : null}
        <Pagination page={list.page} pagination={list.pagination} onPageChange={list.setPage} />
      </Card>
    </>
  );
}
