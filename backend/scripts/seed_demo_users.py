"""Seeds a full set of demo accounts for manual testing (local only): one
of every tier, two fake borrowers, and ONE shared, policy-compliant
password so a human tester can move fast — every account verified,
active, and with must_change_password already OFF (no forced password
change in the way during a test session).

Safe to run twice: every row is looked up by a stable key (email for
users, id_number for borrowers) before being created or updated — a
second run re-syncs the same rows rather than duplicating them.

Refuses to run unless ALLOW_DEMO_SEED=true is set in the environment.
This is a dedicated opt-in flag, never ENVIRONMENT or ENVIRONMENT_LABEL —
both of those are deliberately identical between local and a real
deployment now (ENVIRONMENT stays "production" locally so the secrets/
debug/password startup checks stay just as strict as in production;
ENVIRONMENT_LABEL is blank in both so neither shows a banner), so neither
can tell "local" apart from "real deployment" any more. ALLOW_DEMO_SEED
is set in the local .env.example only — it is never set in
docker-compose.prod.yml or anywhere else production-related, so this
script structurally cannot run against a real deployment regardless of
what ENVIRONMENT/ENVIRONMENT_LABEL happen to be there.
"""
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# "Passw0rd!" alone is only 9 characters — short of the 12-character
# minimum services/password_policy.py enforces everywhere else (CEO seed,
# the mandatory change-password endpoint). Extended, not shortened the
# policy, so this script proves the same real policy every account in
# this app is held to, rather than quietly being an exception to it.
PASSWORD = "Passw0rd!2026"


def main():
    if os.getenv("ALLOW_DEMO_SEED", "").strip().lower() != "true":
        raise SystemExit(
            "refusing to run: ALLOW_DEMO_SEED must be set to 'true' in the environment. "
            "This is only ever set in a local .env — never in docker-compose.prod.yml or "
            "any real deployment — so no fake data or demo accounts can be created there."
        )

    from app import create_app
    from extensions import db
    from models import Borrower, Employee, User
    from services.password_policy import validate_password_strength

    validate_password_strength(PASSWORD, field="demo account password")

    app = create_app()
    with app.app_context():
        ceo = User.query.filter_by(role="ceo").first()
        if ceo is None:
            raise SystemExit(
                "no CEO found — start the stack once first (docker-entrypoint.prod.sh / "
                "docker-compose.override.yml seeds the CEO from .env automatically)"
            )

        def ensure_user(name, email, phone, role, department=None):
            user = User.query.filter_by(email=email).first()
            if user is None:
                user = User(name=name, email=email, phone=phone)
                db.session.add(user)
            user.name = name
            user.phone = phone
            user.role = role
            user.department = department
            user.is_active = True
            user.email_verified = True
            user.must_change_password = False
            user.set_password(PASSWORD)
            db.session.flush()  # user.id is needed below
            return user

        def ensure_employee(user, job_title, salary):
            """One Employee row per user (PRD §2: job title is descriptive
            only, never affects what the account can do). Idempotent — reuses
            an existing linked record (e.g. the CEO's, from seed_ceo.py) or
            an existing unlinked one with the same phone, rather than
            duplicating it."""
            employee = user.employee or Employee.query.filter_by(phone=user.phone).first()
            if employee is None:
                employee = Employee(name=user.name, phone=user.phone, start_date=date.today(), is_active=True)
                db.session.add(employee)
            employee.name = user.name
            employee.job_title = job_title
            employee.salary = Decimal(str(salary))
            employee.phone = user.phone
            employee.email = user.email
            employee.is_active = True
            employee.user_id = user.id
            return employee

        # CEO already exists (seeded from .env's CEO_NAME/CEO_EMAIL by
        # seed_ceo.py on container start) — never create a second one
        # (PRD §2: there can only ever be one). Just give it the same
        # shared demo password and clear must_change_password, so the CEO
        # actually logs in and reaches the app on the first try instead of
        # being stuck behind the mandatory-password-change gate.
        ceo.set_password(PASSWORD)
        ceo.is_active = True
        ceo.email_verified = True
        ceo.must_change_password = False
        db.session.flush()

        roster = [
            (ceo, "CEO", 3_500_000),
            (ensure_user("Grace Mwangi", "headmanager@example.com", "0700100001", "head_manager"), "Head of Operations", 3_200_000),
            (ensure_user("Halima Juma", "hrmanager@example.com", "0700100002", "department_manager", "hr"), "HR Manager", 2_600_000),
            (ensure_user("Peter Kessy", "financemanager@example.com", "0700100003", "department_manager", "finance"), "Finance Manager", 2_600_000),
            (ensure_user("Neema Shirima", "loansmanager@example.com", "0700100004", "department_manager", "loans_credit"), "Loans Manager", 2_600_000),
            (ensure_user("Daudi Mrema", "checker@example.com", "0700100005", "checker", "loans_credit"), "Credit Analyst", 1_500_000),
            (ensure_user("Fatuma Ngowi", "maker@example.com", "0700100006", "maker", "loans_credit"), "Loan Officer", 1_200_000),
            # A second, otherwise-unused Maker — kept spare so a rate-limit
            # test (hammering login attempts until the account locks out)
            # never knocks out the main maker@example.com account other
            # manual testing is using at the same time.
            (ensure_user("Josephat Lema", "maker2@example.com", "0700100008", "maker", "loans_credit"), "Loan Officer (spare — rate-limit testing)", 1_200_000),
        ]
        for user, job_title, salary in roster:
            ensure_employee(user, job_title, salary)
        db.session.commit()

        # Two fake borrowers for local testing — fixed, predictable fake
        # NIDA numbers (20 digits, per PRD §3.2's expected format) and fake
        # phone numbers, looked up by id_number first so a second run
        # updates rather than duplicates them.
        fake_borrowers = [
            ("Demo Borrower One", "0799900001", "19900101000011110001"),
            ("Demo Borrower Two", "0799900002", "19900101000011110002"),
        ]
        for name, phone, id_number in fake_borrowers:
            borrower = Borrower.query.filter_by(id_type="nida", id_number=id_number).first()
            if borrower is None:
                borrower = Borrower(
                    name=name, phone=phone, id_type="nida", id_number=id_number,
                    address="Demo address — local testing only", is_active=True,
                )
                db.session.add(borrower)
            else:
                borrower.name = name
                borrower.phone = phone
        db.session.commit()

        column_widths = (28, 17, len(PASSWORD))
        header = f"{'Email':<28} {'Role':<17} {'Password'}"
        print(f"Seeded demo accounts — shared password for all: {PASSWORD}\n")
        print(header)
        print("-" * (sum(column_widths) + 2))
        for user, _job_title, _salary in roster:
            print(f"{user.email:<28} {user.display_role:<17} {PASSWORD}")
        print()
        print("Fake borrowers (local testing only):")
        for name, phone, id_number in fake_borrowers:
            print(f"  {name} — phone {phone}, NIDA {id_number}")


if __name__ == "__main__":
    main()
