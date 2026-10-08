import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, InlineNote, PageHeader, Select, StatusBadge, fmtNumber } from "../components/lms-ui";
import { LeaveDecisionModal } from "../components/LeaveDecisionModal";
import useAutoRefresh from "../hooks/useAutoRefresh.js";
import useResource from "../hooks/useResource.js";
import { employees, errorMessage, getUser, hasPermission, leaveRequests } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/leave-requests")({
  head: () => ({
    meta: [
      { title: "Leave Requests — Microfinance LMS" },
      { name: "description", content: "Submit and review staff leave requests." },
    ],
  }),
  component: () => (
    <AppShell>
      <LeaveRequestsPage />
    </AppShell>
  ),
});

const PENDING = /pending/i;
const EMPTY = { employee_id: "", leave_type: "Annual", start_date: "", end_date: "", reason: "" };

function LeaveRequestsPage() {
  const user = getUser();
  const canRequestForOthers = hasPermission(user, "leave:manage");
  const canApprove = hasPermission(user, "leave:manage");

  const list = useResource(() => leaveRequests.list(), []);
  const staff = useResource(() => employees.list(), []);
  // Everyone but CEO/manager is only sent their own employee record.
  const ownEmployee = ((staff.data || []) as any[]).find((e) => e.user_id === user?.id);

  const [form, setForm] = useState<any>(EMPTY);
  const [reviewing, setReviewing] = useState<any>(null);

  useAutoRefresh(list.reload);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const employee_id = canRequestForOthers ? Number(form.employee_id) : ownEmployee?.id;
    if (!employee_id) {
      showToast(canRequestForOthers ? "Select an employee." : "No employee record is linked to your account yet.", "danger");
      return;
    }
    if (form.end_date && form.start_date && form.end_date < form.start_date) {
      showToast("The end date cannot be before the start date.", "danger");
      return;
    }
    try {
      await leaveRequests.create({ ...form, employee_id });
      setForm(EMPTY);
      showToast("Leave request submitted.", "success");
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  const rows = list.data || [];
  // The backend says which rows this user may decide (not their own, in scope).
  const pendingRows = rows.filter((r: any) => PENDING.test(r.status) && r.can_decide);

  return (
    <>
      <PageHeader title="Leave requests" description="Submit and review staff leave requests." />
      <InlineNote tone="danger">{list.error}</InlineNote>

      {canApprove ? (
        <Card title="Pending my approval" description={`${fmtNumber(pendingRows.length)} requests`} className="mb-4">
          <DataTable
            rows={pendingRows}
            empty="No leave requests waiting for your approval."
            columns={[
              { key: "employee_name", label: "Employee" },
              { key: "leave_type", label: "Type" },
              { key: "start_date", label: "From" },
              { key: "end_date", label: "To" },
              { key: "reason", label: "Reason" },
              {
                key: "actions",
                label: "",
                render: (r: any) => <Button onClick={() => setReviewing(r)}>Review</Button>,
              },
            ]}
          />
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[1.7fr_1fr]">
        <Card title="Requests">
          <DataTable
            rows={rows}
            empty={list.loading ? "Loading..." : "No leave requests."}
            columns={[
              { key: "employee_name", label: "Employee" },
              { key: "leave_type", label: "Type" },
              { key: "start_date", label: "From" },
              { key: "end_date", label: "To" },
              { key: "creator_name_snapshot", label: "Requested by" },
              { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} reason={r.rejection_reason} /> },
            ]}
            mobileCard={(r: any) => (
              <div>
                <div className="flex items-start justify-between gap-3">
                  <p className="min-w-0 truncate font-medium">{r.employee_name}</p>
                  <p className="shrink-0 text-sm text-muted-foreground">{r.leave_type}</p>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {r.start_date} – {r.end_date}
                </p>
                <div className="mt-2">
                  <StatusBadge status={r.status} reason={r.rejection_reason} />
                </div>
              </div>
            )}
          />
        </Card>
        <Card title="Request leave" description={canRequestForOthers ? "On behalf of any employee." : "For your own employee record."}>
          <form className="space-y-3" onSubmit={create}>
            {canRequestForOthers ? (
              <Field label="Employee">
                <Select value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })}>
                  <option value="">Select employee</option>
                  {(staff.data || [])
                    .filter((row: any) => row.is_active)
                    .map((row: any) => (
                      <option value={row.id} key={row.id}>
                        {row.name}
                      </option>
                    ))}
                </Select>
              </Field>
            ) : null}
            <Field label="Leave type">
              <Input required value={form.leave_type} onChange={(e) => setForm({ ...form, leave_type: e.target.value })} />
            </Field>
            <Field label="Start date">
              <Input type="date" required value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
            </Field>
            <Field label="End date">
              <Input type="date" required value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
            </Field>
            <Field label="Reason">
              <Input value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
            </Field>
            <Button type="submit" className="w-full">
              Submit request
            </Button>
          </form>
        </Card>
      </div>

      {reviewing ? (
        <LeaveDecisionModal leave={reviewing} onClose={() => setReviewing(null)} onDecided={list.reload} />
      ) : null}
    </>
  );
}
