from types import SimpleNamespace

from services.approval import can_approve


def test_creator_cannot_approve_as_admin_or_checker():
    creator = SimpleNamespace(id=7, role="admin")
    record = SimpleNamespace(created_by=7)
    assert can_approve(creator, record) is False

    creator.role = "checker"
    assert can_approve(creator, record) is False


def test_different_checker_or_admin_can_approve():
    record = SimpleNamespace(created_by=7)
    assert can_approve(SimpleNamespace(id=8, role="checker"), record) is True
    assert can_approve(SimpleNamespace(id=8, role="admin"), record) is True


def test_maker_cannot_approve_and_unknown_roles_cannot_approve():
    record = SimpleNamespace(created_by=7)
    assert can_approve(SimpleNamespace(id=8, role="maker"), record) is False
    assert can_approve(SimpleNamespace(id=8, role="other"), record) is False


def test_creator_cannot_approve_loan_penalty_expense_or_payroll():
    creator = SimpleNamespace(id=12, role="checker")
    for record in (
        SimpleNamespace(created_by=12, resource="loan"),
        SimpleNamespace(created_by=12, resource="penalty"),
        SimpleNamespace(created_by=12, resource="expense"),
        SimpleNamespace(created_by=12, resource="payroll"),
    ):
        assert can_approve(creator, record) is False