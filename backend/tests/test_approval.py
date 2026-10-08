"""Unit tests for services/approval.py — the only place maker-checker rules
live. Loans and penalties are the only categories still under maker-checker.
CEO, Head Manager and Department Manager are exempt from the self-approval
block everywhere it applies; checker and maker never are. There is no
self-approved flag/badge/audit distinction of any kind under the tier model
— an exempt approval is simply allowed, recorded like any other decision.

Penalty approval is no longer a checker action at all (a real change from
the previous model): only department_manager and above hold it now.
"""
from types import SimpleNamespace

from services.approval import NOT_AN_APPROVER, SELF_APPROVAL, approval_denial, can_approve


def loan(created_by=7, **extra):
    return SimpleNamespace(created_by=created_by, approval_permission="loans:approve", **extra)


def user(id, role, department=None):
    return SimpleNamespace(id=id, role=role, department=department)


def test_maker_and_checker_cannot_approve_their_own_loan():
    record = loan(created_by=7)
    # A maker is never an approver at all — denied on role, before self ever
    # comes into it (makers don't hold loans:approve in real life either).
    maker = user(7, "maker", "loans_credit")
    checker = user(7, "checker", "loans_credit")
    assert approval_denial(maker, record) == NOT_AN_APPROVER
    assert approval_denial(checker, record) == SELF_APPROVAL
    assert can_approve(maker, record) is False
    assert can_approve(checker, record) is False


def test_ceo_head_manager_and_department_manager_are_exempt_from_self_approval():
    record = loan(created_by=1)
    ceo = user(1, "ceo")
    head_manager = user(1, "head_manager")
    department_manager = user(1, "department_manager", "loans_credit")
    assert approval_denial(ceo, record) is None
    assert approval_denial(head_manager, record) is None
    assert approval_denial(department_manager, record) is None
    assert can_approve(ceo, record) is True
    assert can_approve(head_manager, record) is True
    assert can_approve(department_manager, record) is True
    # No self-approved flag or tracking of any kind — nothing on the record
    # itself reflects that this was a self-approval.
    assert not hasattr(record, "self_approved")


def test_different_checker_head_manager_department_manager_or_ceo_can_approve():
    record = loan(created_by=7)
    assert can_approve(user(8, "checker", "loans_credit"), record) is True
    assert can_approve(user(9, "head_manager"), record) is True
    assert can_approve(user(10, "department_manager", "loans_credit"), record) is True
    assert can_approve(user(11, "ceo"), record) is True


def test_checker_can_approve_any_loan_no_department_restriction():
    """Part 4 simplification: a checker's loan-approval reach no longer
    depends on department at all — any checker can approve any loan."""
    record = loan(created_by=1)
    hr_checker = user(9, "checker", "hr")
    loans_checker = user(9, "checker", "loans_credit")
    finance_checker = user(9, "checker", "finance")
    no_department_checker = user(9, "checker", None)
    assert approval_denial(hr_checker, record) is None
    for checker in (hr_checker, loans_checker, finance_checker, no_department_checker):
        assert can_approve(checker, record) is True


def test_maker_can_never_approve_anything():
    record = loan(created_by=1)
    assert can_approve(user(2, "maker", "loans_credit"), record) is False


def test_checker_can_no_longer_approve_a_penalty_only_department_manager_and_above_can():
    """A real change from the previous model: penalty approval is not a
    checker action any more, regardless of department — only
    department_manager, head_manager and ceo hold it now."""
    penalty = SimpleNamespace(created_by=1, approval_permission="penalties:approve")
    checker = user(9, "checker", "loans_credit")
    department_manager = user(9, "department_manager", "loans_credit")
    assert approval_denial(checker, penalty) == NOT_AN_APPROVER
    assert can_approve(checker, penalty) is False
    assert can_approve(department_manager, penalty) is True


def test_no_checker_ever_approves_a_leave_request_department_manager_and_above_only():
    """Part 4: leave approval belongs to department_manager(hr)/head_manager/
    ceo only — a checker never holds it, in any department, no exception."""
    leave = SimpleNamespace(created_by=1, approval_permission="leave:manage")
    hr_checker = user(2, "checker", "hr")
    general_checker = user(3, "checker", "general")
    hr_department_manager = user(4, "department_manager", "hr")
    assert can_approve(hr_checker, leave) is False
    assert can_approve(general_checker, leave) is False
    assert approval_denial(hr_checker, leave) == NOT_AN_APPROVER
    assert can_approve(hr_department_manager, leave) is True
