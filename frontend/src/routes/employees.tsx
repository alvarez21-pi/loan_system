import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import {
  Button,
  Card,
  Checkbox,
  DataTable,
  Field,
  Input,
  InlineNote,
  Modal,
  MoneyInput,
  PageHeader,
  Select,
  StatusLabel,
  TextLink,
  fmtNumber,
  money,
  useScrollIntoViewOnChange,
} from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { showToast } from "../lib/toast";
import { DEPARTMENT_LABELS, DEPARTMENTS, assignableRolesFor, employees, errorMessage, getUser, hasPermission, roleLabel, users } from "../lib/api";
import EmployeeDeductions from "../components/EmployeeDeductions";

export const Route = createFileRoute("/employees")({
  // ?edit=<id> opens that employee's edit form directly — linked from the
  // Deductions page's Individual tab.
  validateSearch: (search: Record<string, unknown>): { edit?: number | undefined } => ({
    edit: search.edit !== undefined && !Number.isNaN(Number(search.edit)) ? Number(search.edit) : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Employees — Microfinance LMS" },
      { name: "description", content: "Staff register with job titles, salaries and hire dates for payroll processing." },
      { property: "og:title", content: "Employees — Microfinance LMS" },
      { property: "og:description", content: "Staff register with job titles and salaries." },
    ],
  }),
  component: () => (
    <AppShell>
      <EmployeesPage />
    </AppShell>
  ),
});

const SCOPED_ROLES = ["department_manager", "checker", "maker"];
// Department no longer affects what a Checker/Maker can do (Part 6) - their
// department selector here still shows and still saves, just disabled;
// a department_manager's stays fully active and required.
const DEPARTMENT_IS_DESCRIPTIVE_ONLY = ["checker", "maker"];

// Purely descriptive suggestions — job title never grants or restricts access.
const JOB_TITLE_SUGGESTIONS = ["Loan Officer", "Accountant", "Teller", "HR Officer", "Cashier"];
const EMPTY = {
  name: "",
  phone: "",
  email: "",
  job_title: "",
  salary: "",
  hire_date: "",
  // Not every employee needs system access, so a login is opt-in.
  create_user: false,
  role: "maker",
  department: "loans_credit",
};

function EmployeesPage() {
  const user = getUser();
  const search = Route.useSearch();
  const canManage = hasPermission(user, "employees:manage");
  const assignableRoles = assignableRolesFor(user);
  // Creating/linking a LOGIN is an account-creation action, not an HR-record
  // one — available to ceo/head_manager or a department_manager of ANY
  // department (e.g. a Loans Manager), never limited to employees:manage,
  // which is HR-specific (Part 11).
  const canCreateLogins = assignableRoles.length > 0;
  const lockedDepartment = user?.role === "department_manager" ? user.department : null;
  const list = useResource(() => employees.list(), []);
  // Users without an employee record, for "Link to User". Only someone who can manage users can list them.
  const userList = useResource(() => (assignableRoles.length ? users.list() : Promise.resolve({ data: [] })), []);
  const [form, setForm] = useState<any>(EMPTY);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [linking, setLinking] = useState<any>(null);
  const [linkUserId, setLinkUserId] = useState("");
  const [creatingLoginFor, setCreatingLoginFor] = useState<any>(null);
  const [newLoginRole, setNewLoginRole] = useState(assignableRoles[assignableRoles.length - 1] || "maker");
  const [newLoginDepartment, setNewLoginDepartment] = useState(lockedDepartment || "loans_credit");
  const [showInactive, setShowInactive] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const formRef = useScrollIntoViewOnChange<HTMLDivElement>(editingId);

  const all: any[] = list.data || [];
  const rows = showInactive ? all : all.filter((e) => e.is_active);
  const payrollTotal = all.filter((e) => e.is_active).reduce((s: number, e: any) => s + Number(e.salary || 0), 0);
  const unlinkedUsers = (userList.data || []).filter((u: any) => !u.employee_id && u.is_active);
  const creatingLogin = !editingId && form.create_user;

  function validate() {
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "Enter the employee name.";
    if (!/^\+?\d{9,15}$/.test(form.phone.replace(/\s/g, ""))) next.phone = "Enter a valid phone number.";
    if (!form.job_title.trim()) next.job_title = "Enter a job title.";
    if (form.salary === "" || Number(form.salary) < 0) next.salary = "Enter the monthly salary.";
    if (!form.hire_date) next.hire_date = "Select the hire date.";
    if (form.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email.trim())) next.email = "Enter a valid email address.";
    if (creatingLogin && !form.email.trim()) next.email = "An email is needed to create a login.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  function startEdit(row: any) {
    setLinking(null);
    setEditingId(row.id);
    setForm({
      ...EMPTY,
      name: row.name ?? "",
      phone: row.phone ?? "",
      email: row.email ?? "",
      job_title: row.job_title ?? "",
      salary: String(row.salary ?? ""),
      hire_date: row.start_date ?? "",
    });
    setErrors({});
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(EMPTY);
    setErrors({});
  }

  useEffect(() => {
    if (!search.edit || editingId) return;
    const row = (list.data || []).find((r: any) => r.id === search.edit);
    if (row) startEdit(row);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.edit, list.data]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    setBusy(true);
    const fields = {
      name: form.name.trim(),
      phone: form.phone.trim(),
      email: form.email.trim() || undefined,
      job_title: form.job_title.trim(),
      salary: Number(form.salary),
      start_date: form.hire_date,
    };
    try {
      if (editingId) {
        await employees.update(editingId, { ...fields, email: form.email.trim() });
        showToast("Employee updated.", "success");
      } else {
        await employees.create({
          ...fields,
          ...(form.create_user ? { create_user: true, role: form.role, department: form.department } : {}),
        });
        showToast(form.create_user ? `Employee added. A verification email was sent to ${form.email.trim()}.` : "Employee added.", "success");
      }
      cancelEdit();
      list.reload();
      userList.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function setActive(row: any, active: boolean) {
    if (!active && !window.confirm(`Deactivate ${row.name}? They stay on record but drop out of new payroll runs.`)) return;
    try {
      await (active ? employees.reactivate(row.id) : employees.deactivate(row.id));
      showToast(active ? `${row.name} reactivated.` : `${row.name} deactivated.`, "success");
      list.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  async function linkToUser() {
    try {
      await employees.linkUser(linking.id, Number(linkUserId));
      showToast(`${linking.name} is now linked to a login account.`, "success");
      setLinking(null);
      list.reload();
      userList.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  function startCreateLogin(row: any) {
    cancelEdit();
    setLinking(null);
    setCreatingLoginFor(row);
    setNewLoginRole(assignableRoles[assignableRoles.length - 1] || "maker");
    setNewLoginDepartment(lockedDepartment || "loans_credit");
  }

  async function createLoginForEmployee() {
    try {
      await employees.createLogin(creatingLoginFor.id, {
        role: newLoginRole,
        department: SCOPED_ROLES.includes(newLoginRole) ? newLoginDepartment : undefined,
      });
      showToast(`A login was created for ${creatingLoginFor.name}, prefilled with their email. A verification link was sent.`, "success");
      setCreatingLoginFor(null);
      list.reload();
      userList.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  return (
    <>
      <PageHeader title="Employees" description="Staff records used for payroll and leave." />
      <InlineNote tone="danger">{list.error}</InlineNote>

      {linking ? (
        <Modal title={`Link ${linking.name} to a login`} description="Link this employee to a login." onClose={() => setLinking(null)}>
          <div className="space-y-3">
            <Field label="User account" hint={unlinkedUsers.length ? undefined : "Every user already has a record."}>
              <Select value={linkUserId} onChange={(e) => setLinkUserId(e.target.value)}>
                <option value="">Select user</option>
                {unlinkedUsers.map((u: any) => (
                  <option key={u.id} value={u.id}>
                    {u.name} — {u.email} ({u.display_role || roleLabel(u.role, u.department)})
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex gap-2">
              <Button disabled={!linkUserId} onClick={linkToUser}>
                Link to user
              </Button>
              <Button variant="outline" onClick={() => setLinking(null)}>
                Cancel
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}

      {creatingLoginFor ? (
        <Modal
          title={`Create a login for ${creatingLoginFor.name}`}
          description={creatingLoginFor.email ? `Prefilled with ${creatingLoginFor.email}.` : "No email on file — add one first."}
          onClose={() => setCreatingLoginFor(null)}
        >
          <div className="space-y-3">
            <Field label="Tier" hint="Controls access, independent of job title.">
              <Select value={newLoginRole} onChange={(e) => setNewLoginRole(e.target.value)}>
                {assignableRoles.map((role) => (
                  <option key={role} value={role}>
                    {roleLabel(role)}
                  </option>
                ))}
              </Select>
            </Field>
            {SCOPED_ROLES.includes(newLoginRole) ? (
              <Field
                label="Department"
                hint={
                  DEPARTMENT_IS_DESCRIPTIVE_ONLY.includes(newLoginRole)
                    ? "Descriptive only for a Checker or Maker."
                    : undefined
                }
              >
                <Select
                  disabled={Boolean(lockedDepartment) || DEPARTMENT_IS_DESCRIPTIVE_ONLY.includes(newLoginRole)}
                  value={newLoginDepartment}
                  onChange={(e) => setNewLoginDepartment(e.target.value)}
                >
                  {DEPARTMENTS.map((d) => (
                    <option key={d} value={d}>
                      {DEPARTMENT_LABELS[d]}
                    </option>
                  ))}
                </Select>
              </Field>
            ) : null}
            <div className="flex gap-2">
              <Button disabled={!creatingLoginFor.email} onClick={createLoginForEmployee}>
                Create login
              </Button>
              <Button variant="outline" onClick={() => setCreatingLoginFor(null)}>
                Cancel
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}

      <div className={`grid gap-4 ${canManage ? "xl:grid-cols-[1.6fr_1fr]" : ""}`}>
        <Card
          title="Staff list"
          description={`${fmtNumber(all.filter((e) => e.is_active).length)} active employees${canManage ? ` · monthly salaries ${money(payrollTotal)}` : ""}`}
          actions={<Checkbox label="Show inactive" checked={showInactive} onChange={setShowInactive} />}
        >
          <DataTable
            rows={rows}
            empty={list.loading ? "Loading…" : "No employees yet."}
            columns={[
              { key: "name", label: "Name" },
              { key: "phone", label: "Phone" },
              { key: "email", label: "Email", render: (r: any) => r.email || "—" },
              { key: "job_title", label: "Job title" },
              ...(canManage ? [{ key: "salary", label: "Salary", render: (r: any) => money(r.salary) }] : []),
              { key: "start_date", label: "Hired" },
              {
                key: "is_active",
                label: "Status",
                render: (r: any) => <StatusLabel status={r.is_active ? "active" : "inactive"} />,
              },
              {
                key: "linked_user_name",
                label: "Login account",
                render: (r: any) =>
                  r.user_id ? (
                    <span>
                      {r.linked_user_name} <span className="text-xs text-muted-foreground">({roleLabel(r.linked_user_role, r.linked_user_department)})</span>
                      {r.linked_user_verified === false ? <span className="ml-1 text-xs text-muted-foreground">— unverified</span> : null}
                    </span>
                  ) : canCreateLogins && r.is_active ? (
                    <div className="flex flex-wrap items-center gap-3">
                      <TextLink
                        onClick={() => {
                          cancelEdit();
                          setCreatingLoginFor(null);
                          setLinking(r);
                          setLinkUserId("");
                        }}
                      >
                        Link to User
                      </TextLink>
                      <TextLink onClick={() => startCreateLogin(r)}>Create login</TextLink>
                    </div>
                  ) : (
                    "—"
                  ),
              },
              ...(canManage
                ? [
                    {
                      key: "actions",
                      label: "",
                      render: (r: any) => (
                        <div className="flex flex-wrap items-center gap-3">
                          <TextLink onClick={() => startEdit(r)}>Edit</TextLink>
                          {r.is_active ? (
                            r.linked_user_role === "ceo" ? null : (
                              <TextLink tone="danger" onClick={() => setActive(r, false)}>
                                Deactivate
                              </TextLink>
                            )
                          ) : (
                            <TextLink onClick={() => setActive(r, true)}>Reactivate</TextLink>
                          )}
                        </div>
                      ),
                    },
                  ]
                : []),
            ]}
            // Phone pass: name + salary up top, job title/status below, with
            // the same row actions — no separate detail page for an
            // employee record (DESIGN.md §6e's restrained account-list
            // treatment), so the card itself carries the actions.
            mobileCard={(r: any) => (
              <div>
                <div className="flex items-start justify-between gap-3">
                  <p className="min-w-0 truncate font-medium">{r.name}</p>
                  {canManage ? <p className="shrink-0 font-semibold tabular-nums">{money(r.salary)}</p> : null}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {r.job_title} · {r.phone}
                </p>
                <div className="mt-2 flex items-center justify-between gap-3">
                  <StatusLabel status={r.is_active ? "active" : "inactive"} />
                  {canManage ? (
                    <div className="flex flex-wrap items-center gap-3">
                      <TextLink onClick={() => startEdit(r)}>Edit</TextLink>
                      {r.is_active ? (
                        r.linked_user_role === "ceo" ? null : (
                          <TextLink tone="danger" onClick={() => setActive(r, false)}>
                            Deactivate
                          </TextLink>
                        )
                      ) : (
                        <TextLink onClick={() => setActive(r, true)}>Reactivate</TextLink>
                      )}
                    </div>
                  ) : null}
                </div>
              </div>
            )}
          />
        </Card>

        {canManage ? (
          <div ref={formRef}>
          <Card title={editingId ? "Edit employee" : "Add employee"}>
            <form onSubmit={onSubmit} className="space-y-3" noValidate>
              {/* Paired on one row, like every other short-field pair in this
                  app (e.g. loan products' min/max fields) — previously each
                  sat full-width on its own line with no autocomplete hint,
                  which is what made the name->phone tab order read as
                  broken (Part 10). */}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field label="Full name" error={errors.name}>
                  <Input autoComplete="name" value={form.name} onChange={(e: any) => setForm({ ...form, name: e.target.value })} />
                </Field>
                <Field label="Phone" error={errors.phone}>
                  <Input autoComplete="tel" value={form.phone} onChange={(e: any) => setForm({ ...form, phone: e.target.value })} />
                </Field>
              </div>
              <Field label="Email" error={errors.email} hint="Optional — used to email payslips.">
                <Input type="email" value={form.email} onChange={(e: any) => setForm({ ...form, email: e.target.value })} />
              </Field>
              <Field label="Job title" error={errors.job_title} hint="Descriptive only — set tier on Users.">
                <Input
                  list="job-title-suggestions"
                  value={form.job_title}
                  onChange={(e: any) => setForm({ ...form, job_title: e.target.value })}
                />
                <datalist id="job-title-suggestions">
                  {JOB_TITLE_SUGGESTIONS.map((title) => (
                    <option key={title} value={title} />
                  ))}
                </datalist>
              </Field>
              <Field label="Monthly salary" error={errors.salary}>
                <MoneyInput value={form.salary} onValueChange={(v) => setForm({ ...form, salary: v })} />
              </Field>
              <Field label="Hire date" error={errors.hire_date}>
                <Input type="date" value={form.hire_date} onChange={(e: any) => setForm({ ...form, hire_date: e.target.value })} />
              </Field>

              {!editingId ? (
                <>
                  <Checkbox
                    label="Also create a login for this employee"
                    hint="Leave unchecked if they don't sign in."
                    checked={form.create_user}
                    onChange={(create_user) => setForm({ ...form, create_user })}
                  />
                  {form.create_user ? (
                    <>
                      <Field label="Tier" hint="Controls access, independent of job title.">
                        <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                          {assignableRoles.map((role) => (
                            <option key={role} value={role}>
                              {roleLabel(role)}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      {SCOPED_ROLES.includes(form.role) ? (
                        <Field
                          label="Department"
                          hint={
                            DEPARTMENT_IS_DESCRIPTIVE_ONLY.includes(form.role)
                              ? "Descriptive only for a Checker or Maker."
                              : undefined
                          }
                        >
                          <Select
                            disabled={Boolean(lockedDepartment) || DEPARTMENT_IS_DESCRIPTIVE_ONLY.includes(form.role)}
                            value={form.department}
                            onChange={(e) => setForm({ ...form, department: e.target.value })}
                          >
                            {DEPARTMENTS.map((d) => (
                              <option key={d} value={d}>
                                {DEPARTMENT_LABELS[d]}
                              </option>
                            ))}
                          </Select>
                        </Field>
                      ) : null}
                    </>
                  ) : null}
                </>
              ) : null}

              <div className="flex gap-2">
                <Button type="submit" disabled={busy} className="flex-1">
                  {busy ? "Saving…" : editingId ? "Save changes" : "Add employee"}
                </Button>
                {editingId ? (
                  <Button variant="outline" onClick={cancelEdit}>
                    Cancel
                  </Button>
                ) : null}
              </div>
            </form>
          </Card>
          {editingId ? (
            <div className="mt-4">
              <EmployeeDeductions employeeId={editingId} />
            </div>
          ) : null}
          </div>
        ) : null}
      </div>
    </>
  );
}
