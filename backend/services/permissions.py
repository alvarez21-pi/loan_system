"""The tier + department model (final rebuild — Part 0/1/2).

This replaces the earlier per-user permission-matrix checkboxes and their
backing table (UserPermission) ENTIRELY. There is nothing to configure per
user any more beyond which of the five tiers they hold (`role`) and which
department (if any) they're scoped to (`department`) — both plain columns on
User. Every permission check below is a pure function of those two fields.

Five tiers:
    ceo                 — unscoped, everything, untouchable.
    head_manager        — unscoped, everything except creating another
                           head_manager or touching a CEO.
    department_manager  — scoped to exactly one of hr/finance/loans_credit,
                           full access to that department's own modules.
    checker             — a FIXED action set, the same everywhere regardless
                           of department (simplified — see below).
    maker               — a FIXED action set, the same everywhere regardless
                           of department; can never approve anything.

Department -> module mapping is still the source of truth for
department_manager's reach, and for what department_manager/head_manager/ceo
mean by "their department's modules". It no longer gates anything for
checker or maker (a deliberate simplification): their `department` column,
if set at all, is purely a descriptive/reporting tag now, never something
`has_permission()` consults for these two tiers.

Checker and maker (fixed, department-independent):
    maker    — create borrowers, loans, repayments, expenses, penalties, and
               their own leave request. Never approves anything.
    checker  — everything on the maker's create list EXCEPT loans (a checker
               can never create a loan); approve ANY loan, no department
               restriction. Never approves a leave request under any
               circumstance — leave approval is department_manager(hr)/
               head_manager/ceo only. Never approves a penalty either
               (unchanged: that stays department_manager and above).
"""

ROLES = ("ceo", "head_manager", "department_manager", "checker", "maker")
DEPARTMENTS = ("hr", "finance", "loans_credit", "general")

UNSCOPED_ROLES = {"ceo", "head_manager"}
SCOPED_ROLES = {"department_manager", "checker", "maker"}
# Roles anyone can ever be assigned to (ceo is only ever seeded, never handed out).
ASSIGNABLE_ROLES = {"head_manager", "department_manager", "checker", "maker"}

DEPARTMENT_LABELS = {
    "hr": "HR",
    "finance": "Finance",
    "loans_credit": "Loans Credit",
    "general": "General",
}

# Part 3: a department_manager is always shown by this derived title, never
# the raw role+department pair ("Loans Manager", not "Loans Credit Manager").
DEPARTMENT_MANAGER_TITLES = {
    "hr": "HR Manager",
    "finance": "Finance Manager",
    "loans_credit": "Loans Manager",
    "general": "General Manager",
}

ROLE_LABELS = {
    "ceo": "CEO",
    "head_manager": "Head Manager",
    "department_manager": "Department Manager",
    "checker": "Checker",
    "maker": "Maker",
}


def role_label(role, department=None):
    """Human-readable title for a user row. A department_manager is always
    shown by their derived title, never as a raw role+department pair."""
    if role == "department_manager":
        return DEPARTMENT_MANAGER_TITLES.get(department, "Department Manager")
    return ROLE_LABELS.get(role, role)


# Part 2 — which modules each department reaches. "general" is the broad
# catch-all used for ceo/head_manager's (unscoped) reach and for a
# checker/maker/department_manager who deliberately needs wider access than
# one department; a department_manager should normally be hr/finance/
# loans_credit specifically, per Part 1.
DEPARTMENT_MODULES = {
    "hr": {"employees", "payroll", "leave_requests"},
    "finance": {"expenses", "capital", "assets", "reports"},
    "loans_credit": {"borrowers", "loans", "repayments", "penalties", "calculator"},
    "general": {
        "borrowers", "loans", "repayments", "penalties", "calculator",
        "employees", "payroll", "leave_requests", "expenses", "capital",
        "assets", "reports",
    },
}


def modules_for(department):
    return DEPARTMENT_MODULES.get(department, set())


# The fixed set of modules a checker/maker's action set ever touches,
# department-independent (Part 4). Notably excludes employees/payroll/
# capital/assets/reports — neither tier reaches those no matter what.
MAKER_CHECKER_MODULES = {"borrowers", "loans", "repayments", "expenses", "penalties", "leave_requests", "calculator"}


def has_module_access(user, module):
    """Whether this user's tier reaches `module` AT ALL (any action). Used
    for read-type gating and nav visibility, since reads on borrowers/loans/
    penalties/assets/calculator stay open to any authenticated user at the
    API (see ARCHITECTURE.md's "known simplification") — this is what
    decides whether showing that page makes sense for this account, not a
    server-enforced read boundary."""
    if user is None:
        return False
    if user.role in UNSCOPED_ROLES:
        return True
    if user.role in ("checker", "maker"):
        return module in MAKER_CHECKER_MODULES
    if user.role == "department_manager":
        return module in modules_for(user.department)
    return False


# Every "<area>:<verb>" permission string used across the codebase, mapped to
# the module it belongs to. This is the ONLY place that mapping lives.
PERMISSION_MODULE = {
    "borrowers:view": "borrowers", "borrowers:manage": "borrowers",
    "loans:view": "loans", "loans:create": "loans", "loans:approve": "loans",
    # Loan products are configuration for the loans module, not a separate
    # one — a Loans Manager (department_manager, loans_credit) manages them
    # the same way they manage everything else in their department (Part 4.1).
    "loan_products:manage": "loans",
    # Early-settlement interest discount (Part 4) - Loans Manager (department_
    # manager, loans_credit), Head Manager or CEO only. Never a Checker or
    # Maker: deliberately NOT added to either's fixed permission set below.
    "settlement:discount": "loans",
    "penalties:view": "penalties", "penalties:create": "penalties", "penalties:approve": "penalties",
    "repayments:record": "repayments",
    "calculator:use": "calculator",
    "reports:view": "reports", "reports:financial": "reports",
    "capital:view": "capital", "capital:manage": "capital",
    "assets:manage": "assets",
    "expenses:manage": "expenses",
    "employees:manage": "employees",
    "payroll:manage": "payroll",
    "leave:request": "leave_requests", "leave:manage": "leave_requests",
}

# Checker and maker never get blanket module access the way a
# department_manager does — each holds exactly this fixed, small set of
# create/approve verbs, the SAME everywhere regardless of department (Part 4
# — a simplification from the earlier department-gated design). Nothing
# else, ever: neither tier ever reaches reports/assets/capital/employees/
# payroll, and NEITHER approves a penalty or a leave request — only
# department_manager and above hold those.
CHECKER_PERMISSIONS = {
    "loans:approve",  # ANY loan, no department restriction
    "borrowers:manage", "repayments:record", "expenses:manage", "penalties:create", "leave:request",  # create
}
MAKER_PERMISSIONS = {
    "borrowers:manage", "loans:create", "repayments:record",
    "expenses:manage", "penalties:create", "leave:request",
}
# HARD RULES, no exception (Part 4): a checker can never create a loan and
# can never approve a leave request; a maker can never approve anything.
# Enforced below by simply never including them in the sets above, plus
# these assertions so a future edit can't reintroduce any of them by accident.
assert "loans:create" not in CHECKER_PERMISSIONS
assert "leave:manage" not in CHECKER_PERMISSIONS
assert not any(p.endswith(":approve") for p in MAKER_PERMISSIONS)

# Administrative capabilities that sit outside the department-module system
# entirely — unscoped, ceo/head_manager only.
GLOBAL_ONLY_PERMISSIONS = {"users:manage", "audit:view", "backup:manage"}

PERMISSIONS = tuple(sorted(set(PERMISSION_MODULE) | GLOBAL_ONLY_PERMISSIONS))


def has_permission(user, permission):
    """The one function every endpoint calls.

    ceo/head_manager: everything, unconditionally.
    department_manager: everything within their one department's modules.
    checker/maker: a fixed action set (CHECKER_PERMISSIONS/MAKER_PERMISSIONS)
    — department plays NO part in this decision for these two tiers (Part 4);
    it is at most a descriptive tag on the account, never consulted here.
    """
    if user is None:
        return False
    if user.role in UNSCOPED_ROLES:
        return True  # ceo, head_manager: everything, always

    if permission == "calculator:use" and user.role in ("checker", "maker"):
        # Bundled with loan creation/approval, both now department-independent
        # for these two tiers — so the embedded schedule preview follows suit.
        return True
    if permission == "calculator:use":
        return has_module_access(user, "calculator")

    if permission in GLOBAL_ONLY_PERMISSIONS:
        return False  # only ceo/head_manager reach these (handled above)

    module = PERMISSION_MODULE.get(permission)
    if module is None:
        return False

    if user.role == "department_manager":
        return module in modules_for(user.department)

    if user.role == "checker":
        return permission in CHECKER_PERMISSIONS

    if user.role == "maker":
        return permission in MAKER_PERMISSIONS

    return False


def has_any_permission(user, *permissions):
    return any(has_permission(user, permission) for permission in permissions)


# ------------------------------------------------------------- hierarchy
# Part 1's account creation/management hierarchy. This is deliberately
# separate from has_permission() above: who may hand out a given tier is a
# stricter, hand-written rule, not a generic "manage" permission.

def can_create_tier(actor, target_role, target_department=None):
    """Whether `actor` may create an account of `target_role` (in
    `target_department`, for a scoped role)."""
    if actor is None or target_role not in ASSIGNABLE_ROLES:
        return False
    if target_role in SCOPED_ROLES and target_department not in DEPARTMENTS:
        return False  # a scoped tier always needs a real department
    if actor.role == "ceo":
        return True
    if actor.role == "head_manager":
        return target_role in {"department_manager", "checker", "maker"}
    if actor.role == "department_manager":
        return target_role in {"checker", "maker"} and target_department == actor.department
    return False  # checker, maker: can create nobody


def can_manage_user(actor, target):
    """Whether actor may edit/deactivate/delete/reassign this EXISTING user.
    The CEO is guarded separately and unconditionally (routes/users.py's
    guard_ceo) — this never needs to special-case it, but does anyway for
    safety if called directly."""
    if actor is None or target is None or target.role == "ceo":
        return False
    return can_create_tier(actor, target.role, target.department)


def assignable_roles_for(actor):
    """Tiers this actor may hand out — drives the create-user form (Part 3)."""
    if actor is None:
        return []
    if actor.role == "ceo":
        return ["head_manager", "department_manager", "checker", "maker"]
    if actor.role == "head_manager":
        return ["department_manager", "checker", "maker"]
    if actor.role == "department_manager":
        return ["checker", "maker"]
    return []
