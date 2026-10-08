"""Maker-checker, still narrowed to loans and penalties only.

`has_permission()` already encodes both "can this tier ever hold this
permission" (role) and, for a department_manager only, "is the record's
module in their department" (scope) — the approve/reject endpoints need to
tell those two failure reasons apart for a clear message (DESIGN.md's error
table), so `_approver_capable()` below re-derives the role-only half.

created_by can never equal approved_by for a checker or a maker — no
exception. CEO, Head Manager and Department Manager ARE exempt from that one
rule: they may approve a loan or penalty they created themselves. There is no
"self-approved" badge, flag or audit distinction of any kind for this any
more — the approval is simply allowed and recorded like any other.

Simplified checker/maker rule (Part 4): a checker approves ANY loan, no
department restriction — and NEVER approves a leave request or a penalty,
under any circumstance. A maker never approves anything. Only
department_manager and above approve a penalty or a leave request.
"""
from services.permissions import has_permission

SELF_APPROVAL_EXEMPT_ROLES = {"ceo", "head_manager", "department_manager"}
FULL_ACCESS_ROLES = {"ceo", "head_manager", "department_manager"}

SELF_APPROVAL = "self"
NOT_AN_APPROVER = "role"
OUT_OF_SCOPE = "scope"


def _approver_capable(user, permission):
    """Whether this user's TIER could ever hold `permission` — used only to
    distinguish "wrong role" from "right role, wrong department" (which can
    still happen for a department_manager) for the error message."""
    if user.role in FULL_ACCESS_ROLES:
        return True
    if user.role == "checker":
        return permission == "loans:approve"  # never leave, never a penalty
    return False  # maker never approves anything


def approval_denial(user, record):
    """Return None if user may approve/reject record, else why not.

    One of SELF_APPROVAL, NOT_AN_APPROVER or OUT_OF_SCOPE. This is the only
    place these rules live — every approve/reject endpoint goes through it.
    """
    if user is None or record is None:
        return NOT_AN_APPROVER

    permission = getattr(record, "approval_permission", None)
    if not _approver_capable(user, permission):
        return NOT_AN_APPROVER
    if not has_permission(user, permission):
        return OUT_OF_SCOPE

    creator_id = getattr(record, "created_by", None)
    if creator_id is not None and getattr(user, "id", None) == creator_id:
        if user.role in SELF_APPROVAL_EXEMPT_ROLES:
            return None
        return SELF_APPROVAL

    return None


def can_approve(user, record):
    """Return whether user can approve record under the (narrowed) maker-checker rule."""
    return approval_denial(user, record) is None
