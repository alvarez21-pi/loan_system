"""Wipe every user and business record, then reseed just the CEO from
environment variables (Phase 7 item 2).

Refuses to run unless ALL of:
- --yes is passed explicitly on the command line (confirms the operator
  means it — no environment variable can substitute for this).
- ENVIRONMENT_LABEL is set (the same variable that puts a visible banner
  on every page — if this deployment doesn't show one, this script
  refuses to touch its data).
- ENVIRONMENT is not "production", no matter what else is set.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", action="store_true",
        help="confirm this wipes ALL users and business data — required, no default",
    )
    args = parser.parse_args(argv)

    from services.startup_safety import environment_name

    environment = environment_name()
    if environment == "production":
        raise SystemExit("refusing to run: ENVIRONMENT=production")
    if not os.getenv("ENVIRONMENT_LABEL", "").strip():
        raise SystemExit(
            "refusing to run: ENVIRONMENT_LABEL must be set (this is the same "
            "variable that shows the on-page banner — if this deployment isn't "
            "visibly marked as a test environment, this script won't touch it)"
        )
    if not args.yes:
        raise SystemExit("refusing to run: pass --yes to confirm this wipes all users and business data")

    from app import create_app
    from extensions import db
    from models import (
        AssetType,
        Employee,
        LeaveRequest,
        Loan,
        PaymentSchedule,
        PayrollBatch,
        PayrollRun,
        Penalty,
        Repayment,
        User,
    )

    app = create_app()
    with app.app_context():
        # Children before parents; SET NULL foreign keys handle the rest.
        for model in (
            Repayment, PaymentSchedule, Penalty,
        ):
            model.query.delete()
        from models import Loan as _Loan, LoanProduct, Borrower, Asset, Expense, CapitalEntry
        _Loan.query.delete()
        LoanProduct.query.delete()
        Borrower.query.delete()
        PayrollRun.query.delete()
        PayrollBatch.query.delete()
        LeaveRequest.query.delete()
        Employee.query.delete()
        Asset.query.delete()
        AssetType.query.delete()
        Expense.query.delete()
        CapitalEntry.query.delete()
        from models import AuditLog
        AuditLog.query.delete()
        User.query.delete()
        db.session.commit()
        print("wiped: all users and business data")

    import seed_ceo
    seed_ceo.main()


if __name__ == "__main__":
    main()
