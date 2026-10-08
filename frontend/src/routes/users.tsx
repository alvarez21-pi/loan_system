import { createFileRoute } from "@tanstack/react-router";
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
  MoneyInput,
  PageHeader,
  Pagination,
  Select,
  SearchInput,
  StatusLabel,
  TextLink,
} from "../components/lms-ui";
import usePaginatedResource from "../hooks/usePaginatedResource.js";
import useResource from "../hooks/useResource.js";
import { showToast } from "../lib/toast";
import {
  DEPARTMENT_LABELS,
  DEPARTMENTS,
  assignableRolesFor,
  auth,
  employees,
  errorMessage,
  getUser,
  roleLabel,
  users,
} from "../lib/api";

export const Route = createFileRoute("/users")({
  head: () => ({
    meta: [
      { title: "Users — Microfinance LMS" },
      {
        name: "description",
        content: "Create and manage staff accounts.",
      },
    ],
  }),
  component: () => (
    <AppShell>
      <UsersPage />
    </AppShell>
  ),
});

const SCOPED_ROLES = ["department_manager", "checker", "maker"];
const LINKABLE_ROLES = ["head_manager", "department_manager", "checker", "maker"];
// Department no longer gates anything for these two tiers — it's shown and
// saved as a descriptive/reporting tag only (Part 6), so the selector is
// disabled for them rather than offered as a real choice.
const DEPARTMENT_IS_DESCRIPTIVE_ONLY = ["checker", "maker"];

function emptyForm(assignableRoles: string[], defaultDepartment: string) {
  const role = assignableRoles[assignableRoles.length - 1] || "maker";
  return {
    name: "",
    email: "",
    phone: "",
    role,
    department: SCOPED_ROLES.includes(role) ? defaultDepartment : "",
    job_title: "",
    salary: "",
    employee_option: "create" as "create" | "link" | "none",
    employee_id: "",
  };
}

// Job title is purely descriptive (Employee record) — separate from the
// permission tier. These are only ever a starting suggestion: picking one
// pre-fills the tier field once, but both stay independently editable.
const JOB_TITLE_SUGGESTIONS = ["Loan Officer", "Accountant", "Teller", "HR Officer", "Cashier"];
const JOB_TITLE_ROLE_HINT: Record<string, string> = {
  "Loan Officer": "maker",
  Accountant: "checker",
};

function daysUntilDeletion(deactivatedAt: string | null | undefined, retentionDays: number) {
  if (!deactivatedAt) return null;
  const deletesAt = new Date(deactivatedAt).getTime() + retentionDays * 24 * 60 * 60 * 1000;
  return Math.ceil((deletesAt - Date.now()) / (24 * 60 * 60 * 1000));
}

/** Department select that goes inert (greyed out) once the chosen tier is a
 * Checker or Maker — it still carries a value that gets saved, just not one
 * the user can change here, because it no longer affects what the account
 * can do (Part 6). Fully active and required for a Department Manager. */
function DepartmentField({
  role,
  value,
  onChange,
  locked,
}: {
  role: string;
  value: string;
  onChange: (value: string) => void;
  locked: boolean;
}) {
  if (!SCOPED_ROLES.includes(role)) return null;
  const descriptiveOnly = DEPARTMENT_IS_DESCRIPTIVE_ONLY.includes(role);
  const disabled = locked || descriptiveOnly;
  return (
    <Field
      label="Department"
      hint={
        descriptiveOnly
          ? "Descriptive only for a Checker or Maker."
          : locked
            ? "Fixed to your own department."
            : "Which modules this account can reach."
      }
    >
      <Select
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={disabled ? "opacity-60" : ""}
      >
        {DEPARTMENTS.map((d) => (
          <option key={d} value={d}>
            {DEPARTMENT_LABELS[d]}
          </option>
        ))}
      </Select>
    </Field>
  );
}

function UsersPage() {
  const currentUser = getUser();
  const isCeo = currentUser?.role === "ceo";
  const assignableRoles = assignableRolesFor(currentUser);
  const canManageUsers = assignableRoles.length > 0;
  // A department_manager may only ever create/manage their own department's
  // staff (Part 1) — the department field is fixed for them, not a choice.
  const lockedDepartment =
    currentUser?.role === "department_manager" ? currentUser.department : null;

  const [retentionDays, setRetentionDays] = useState(30);
  // The create-user form's "link to existing employee" picker needs EVERY
  // unlinked employee on screen at once (never just the current page), kept
  // as its own unpaginated load — the users table itself is the
  // server-paginated/searchable one (Phase 5).
  const staffList = useResource(
    () => (canManageUsers ? employees.list() : Promise.resolve({ data: [] })),
    [canManageUsers],
  );
  const staff = staffList.data || [];
  const list = usePaginatedResource(
    (params: any) =>
      (canManageUsers
        ? users.list(params).then((result: any) => {
            setRetentionDays(result.retentionDays ?? 30);
            return result;
          })
        : Promise.resolve({ data: [], pagination: null })) as Promise<{
        data: any[];
        pagination: any;
      }>,
    [canManageUsers],
  );
  const rows = list.data || [];
  const [form, setForm] = useState<any>(() =>
    emptyForm(assignableRoles, lockedDepartment || "general"),
  );
  const [roleTouched, setRoleTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [linking, setLinking] = useState<any>(null);
  const [linkEmployeeId, setLinkEmployeeId] = useState("");
  // Editing a user is its own self-contained modal (Part 7) — never content
  // that silently appears somewhere else on the page.
  const [editing, setEditing] = useState<any>(null);
  const [editRole, setEditRole] = useState("");
  const [editDepartment, setEditDepartment] = useState("");
  const [editBusy, setEditBusy] = useState(false);

  function reloadAll() {
    list.reload();
    staffList.reload();
  }

  if (!canManageUsers) {
    return <InlineNote tone="danger">Ceo, head manager, or department manager role required.</InlineNote>;
  }

  const canLinkEmployee = LINKABLE_ROLES.includes(form.role);
  const unlinkedEmployees = staff.filter((e: any) => !e.user_id && e.is_active);

  function departmentForRole(role: string, current: string) {
    if (!SCOPED_ROLES.includes(role)) return "";
    if (lockedDepartment) return lockedDepartment;
    if (DEPARTMENT_IS_DESCRIPTIVE_ONLY.includes(role)) return current || "general";
    return current || "loans_credit";
  }

  function pickJobTitle(title: string) {
    const next: any = { ...form, job_title: title };
    const suggestedRole = JOB_TITLE_ROLE_HINT[title];
    if (!roleTouched && suggestedRole && assignableRoles.includes(suggestedRole)) {
      next.role = suggestedRole;
      next.department = departmentForRole(suggestedRole, next.department);
    }
    setForm(next);
  }

  function changeRole(role: string) {
    setRoleTouched(true);
    setForm({ ...form, role, department: departmentForRole(role, form.department) });
  }

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const payload: any = {
        name: form.name,
        email: form.email,
        phone: form.phone,
        role: form.role,
        department: SCOPED_ROLES.includes(form.role) ? form.department : undefined,
        employee_option: canLinkEmployee ? form.employee_option : "none",
      };
      if (canLinkEmployee && form.employee_option === "create") {
        payload.job_title = form.job_title || undefined;
        payload.salary = form.salary === "" ? undefined : Number(form.salary);
      }
      if (canLinkEmployee && form.employee_option === "link") {
        payload.employee_id = Number(form.employee_id);
      }
      await auth.register(payload);
      showToast(`Verification email sent to ${form.email}`, "success");
      setForm(emptyForm(assignableRoles, lockedDepartment || "general"));
      setRoleTouched(false);
      reloadAll();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>, success?: string) {
    try {
      await fn();
      if (success) showToast(success, "success");
      reloadAll();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  function startLink(row: any) {
    setLinking(row);
    setLinkEmployeeId("");
  }

  function startEdit(row: any) {
    setEditing(row);
    setEditRole(row.role);
    setEditDepartment(row.department || departmentForRole(row.role, ""));
  }

  async function saveEdit() {
    setEditBusy(true);
    try {
      await users.updateRole(
        editing.id,
        editRole,
        SCOPED_ROLES.includes(editRole) ? editDepartment : null,
      );
      showToast(`${editing.name}'s access was updated.`, "success");
      setEditing(null);
      reloadAll();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setEditBusy(false);
    }
  }

  // Mirrors the backend's can_manage_user(): whether the signed-in actor may
  // touch this row at all (edit tier/department, deactivate, delete) — the
  // CEO stays fully uneditable by anyone but themself, exactly as before.
  function canModify(row: any) {
    if (row.role === "ceo") return false;
    if (isCeo) return true;
    if (currentUser?.role === "head_manager") return row.role !== "head_manager";
    if (currentUser?.role === "department_manager")
      return (
        SCOPED_ROLES.includes(row.role) &&
        row.role !== "department_manager" &&
        row.department === currentUser.department
      );
    return false;
  }

  return (
    <>
      <PageHeader
        title="User management"
        description="Create and manage staff accounts."
      />

      {editing ? (
        <Modal
          title={`Edit ${editing.name}`}
          description="Change this account's tier and department."
          onClose={() => setEditing(null)}
        >
          <div className="space-y-3">
            <Field label="Tier">
              <Select
                value={editRole}
                onChange={(e) => {
                  const role = e.target.value;
                  setEditRole(role);
                  setEditDepartment(departmentForRole(role, editDepartment));
                }}
              >
                {Array.from(new Set([...assignableRoles, editing.role])).map((role) => (
                  <option key={role} value={role}>
                    {roleLabel(role)}
                  </option>
                ))}
              </Select>
            </Field>
            <DepartmentField
              role={editRole}
              value={editDepartment}
              onChange={setEditDepartment}
              locked={Boolean(lockedDepartment)}
            />
            <div className="flex gap-2 pt-2">
              <Button disabled={editBusy} onClick={saveEdit} className="flex-1">
                {editBusy ? "Saving…" : "Save changes"}
              </Button>
              <Button variant="outline" onClick={() => setEditing(null)}>
                Cancel
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}

      {linking ? (
        <Modal
          title={`Link ${linking.name} to an employee record`}
          description="Link to an existing employee."
          onClose={() => setLinking(null)}
        >
          <div className="space-y-3">
            <Field
              label="Employee"
              hint={
                unlinkedEmployees.length
                  ? undefined
                  : "Every employee is already linked."
              }
            >
              <Select value={linkEmployeeId} onChange={(e) => setLinkEmployeeId(e.target.value)}>
                <option value="">Select employee</option>
                {unlinkedEmployees.map((e: any) => (
                  <option key={e.id} value={e.id}>
                    {e.name} — {e.job_title}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex gap-2">
              <Button
                disabled={!linkEmployeeId}
                onClick={() =>
                  act(async () => {
                    await users.linkEmployee(linking.id, Number(linkEmployeeId));
                    setLinking(null);
                  }, `${linking.name} is now linked to their employee record.`)
                }
              >
                Link to employee
              </Button>
              <Button variant="outline" onClick={() => setLinking(null)}>
                Cancel
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[1fr_1.7fr]">
        <Card title="Create staff user">
          <form className="space-y-3" onSubmit={createUser}>
            <Field label="Name">
              <Input
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>
            <Field label="Email">
              <Input
                required
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </Field>
            <Field label="Phone">
              <Input
                required
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
              />
            </Field>
            <Field
              label="Tier"
              hint="Controls access, independent of job title."
            >
              <Select value={form.role} onChange={(e) => changeRole(e.target.value)}>
                {assignableRoles.map((role) => (
                  <option key={role} value={role}>
                    {roleLabel(role)}
                  </option>
                ))}
              </Select>
            </Field>
            <DepartmentField
              role={form.role}
              value={form.department}
              onChange={(department) => setForm({ ...form, department })}
              locked={Boolean(lockedDepartment)}
            />
            {canLinkEmployee ? (
              <Field label="Employee record">
                <div className="space-y-1">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="employee_option"
                      checked={form.employee_option === "create"}
                      onChange={() => setForm({ ...form, employee_option: "create" })}
                    />
                    Create new employee record
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="employee_option"
                      checked={form.employee_option === "link"}
                      onChange={() => setForm({ ...form, employee_option: "link" })}
                    />
                    Link to existing employee
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="employee_option"
                      checked={form.employee_option === "none"}
                      onChange={() => setForm({ ...form, employee_option: "none" })}
                    />
                    No employee record
                  </label>
                </div>
              </Field>
            ) : null}
            {canLinkEmployee && form.employee_option === "create" ? (
              <>
                <Field label="Job title" hint="Descriptive only — never affects permissions.">
                  <Input
                    value={form.job_title}
                    placeholder="e.g. Loan Officer"
                    onChange={(e) => setForm({ ...form, job_title: e.target.value })}
                  />
                  <div className="mt-2 flex flex-wrap gap-1">
                    {JOB_TITLE_SUGGESTIONS.map((title) => (
                      <button
                        key={title}
                        type="button"
                        className="lms-badge lms-badge-neutral cursor-pointer"
                        onClick={() => pickJobTitle(title)}
                      >
                        {title}
                      </button>
                    ))}
                  </div>
                </Field>
                <Field
                  label="Monthly salary"
                  hint="Optional — set later on Employees."
                >
                  <MoneyInput
                    value={form.salary}
                    onValueChange={(salary) => setForm({ ...form, salary })}
                  />
                </Field>
              </>
            ) : null}
            {canLinkEmployee && form.employee_option === "link" ? (
              <Field
                label="Employee"
                hint={
                  unlinkedEmployees.length
                    ? undefined
                    : "No employees available to link."
                }
              >
                <Select
                  value={form.employee_id}
                  onChange={(e) => setForm({ ...form, employee_id: e.target.value })}
                >
                  <option value="">Select employee</option>
                  {unlinkedEmployees.map((e: any) => (
                    <option key={e.id} value={e.id}>
                      {e.name} — {e.job_title}
                    </option>
                  ))}
                </Select>
              </Field>
            ) : null}
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Creating..." : "Create user"}
            </Button>
          </form>
        </Card>
        {/* min-w-0 lets this column's own table scroll horizontally INSIDE
            itself (DataTable already wraps in overflow-x-auto) instead of
            the grid track growing to the table's full width and pushing the
            whole page sideways (Part 13.1). */}
        <Card
          title="Existing users"
          className="min-w-0"
          description={`${list.pagination ? list.pagination.total : rows.length} records`}
          actions={
            <SearchInput
              value={list.q}
              onChange={list.setQ}
              placeholder="Search by name, email or phone"
            />
          }
        >
          <ListStatus
            loading={list.loading}
            error={list.error}
            empty={!list.loading && !list.error && rows.length === 0}
            emptyMessage="No users."
          />
          {!list.loading && !list.error && rows.length > 0 ? (
            <DataTable
              rows={rows}
              sort={list.sort}
              order={list.order}
              onSort={list.toggleSort}
              columns={[
                { key: "name", label: "Name", sortKey: "name" },
                { key: "email", label: "Email", sortKey: "email" },
                {
                  key: "role",
                  label: "Tier",
                  sortKey: "role",
                  render: (r: any) => (
                    <span>{r.display_role || roleLabel(r.role, r.department)}</span>
                  ),
                },
                {
                  key: "department",
                  label: "Department",
                  render: (r: any) =>
                    r.department ? DEPARTMENT_LABELS[r.department] || r.department : "—",
                },
                {
                  key: "employee_name",
                  label: "Employee record",
                  render: (r: any) =>
                    r.employee_name ? (
                      r.employee_name
                    ) : canModify(r) || r.role === "ceo" ? (
                      <TextLink onClick={() => startLink(r)}>Link to Employee</TextLink>
                    ) : (
                      "—"
                    ),
                },
                {
                  key: "email_verified",
                  label: "Verified",
                  render: (r: any) => (
                    <StatusLabel status={r.email_verified ? "approved" : "pending"} />
                  ),
                },
                {
                  key: "is_active",
                  label: "Status",
                  render: (r: any) => {
                    if (r.is_active) return <StatusLabel status="active" />;
                    const days = daysUntilDeletion(r.deactivated_at, retentionDays);
                    return (
                      <div>
                        <StatusLabel status="rejected" />
                        {days !== null ? (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {days > 0
                              ? `${days} day${days === 1 ? "" : "s"} until permanent deletion`
                              : "Pending permanent deletion"}
                          </p>
                        ) : null}
                      </div>
                    );
                  },
                },
                {
                  // Every action for a row lives together in one place — a
                  // pending (unverified) user's Resend/Deactivate are just as
                  // visible as any other row's actions (Part 13.2). Small text
                  // links, not full buttons, for this dense account list
                  // (Part 6.1).
                  key: "actions",
                  label: "",
                  render: (r: any) => {
                    if (r.role === "ceo") return null;
                    if (!canModify(r)) return null;
                    return (
                      <div className="flex flex-wrap items-center gap-3">
                        <TextLink onClick={() => startEdit(r)}>Edit</TextLink>
                        {!r.email_verified ? (
                          <TextLink
                            onClick={() =>
                              act(
                                () => users.resendVerification(r.id),
                                `A new verification link was sent to ${r.email}.`,
                              )
                            }
                          >
                            Resend link
                          </TextLink>
                        ) : null}
                        {r.id === currentUser?.id ? null : r.is_active ? (
                          <TextLink tone="danger" onClick={() => act(() => users.deactivate(r.id))}>
                            Deactivate
                          </TextLink>
                        ) : (
                          <TextLink onClick={() => act(() => users.reactivate(r.id))}>
                            Reactivate
                          </TextLink>
                        )}
                      </div>
                    );
                  },
                },
              ]}
              mobileCard={(r: any) => (
                <div>
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 truncate font-medium">{r.name}</p>
                    <p className="shrink-0 text-xs text-muted-foreground">{r.display_role || roleLabel(r.role, r.department)}</p>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{r.email}</p>
                  <div className="mt-2 flex items-center justify-between gap-3">
                    <StatusLabel status={r.is_active ? "active" : "rejected"} />
                    {r.role !== "ceo" && canModify(r) ? (
                      <div className="flex flex-wrap items-center gap-3">
                        <TextLink onClick={() => startEdit(r)}>Edit</TextLink>
                        {r.id === currentUser?.id ? null : r.is_active ? (
                          <TextLink tone="danger" onClick={() => act(() => users.deactivate(r.id))}>
                            Deactivate
                          </TextLink>
                        ) : (
                          <TextLink onClick={() => act(() => users.reactivate(r.id))}>Reactivate</TextLink>
                        )}
                      </div>
                    ) : null}
                  </div>
                </div>
              )}
            />
          ) : null}
          <Pagination page={list.page} pagination={list.pagination} onPageChange={list.setPage} />
        </Card>
      </div>
    </>
  );
}
