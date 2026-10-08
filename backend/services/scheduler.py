import os
import tempfile
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from extensions import db
from models import AuditLog, BackupLog, Loan, PaymentSchedule, User
from routes.operations import carry_over_overdue_partial_periods, delay_missed_schedule_periods
from services.backup import write_nightly_backup
from services.email_client import send_email
from services.loan_calculator import local_today

_scheduler = None

SYSTEM_ACTOR_NAME = "System"
SYSTEM_ACTOR_EMAIL = "system@internal"

# Phase 2 item 1: the backend now runs under gunicorn with multiple worker
# PROCESSES (not threads) — each one imports this module fresh, so the
# module-level `_scheduler is not None` check below only ever protects ONE
# of them from starting its own copy twice; it does nothing to stop a
# SECOND worker from also starting its own scheduler, which would fire
# every reminder/purge job once per worker. An atomic O_CREAT|O_EXCL file
# create is race-safe across processes on the same filesystem. /tmp is
# ephemeral (unlike the persistent uploads volume), so a stale lock never
# survives a container restart.
_SCHEDULER_LOCK_PATH = os.path.join(tempfile.gettempdir(), "lms-scheduler.lock")


def _acquire_scheduler_lock():
    try:
        fd = os.open(_SCHEDULER_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def retention_days():
    try:
        return int(os.getenv("USER_DELETION_RETENTION_DAYS", "30"))
    except (TypeError, ValueError):
        return 30


def reconcile_reminders(app):
    with app.app_context():
        today = local_today()
        upcoming = PaymentSchedule.query.filter(
            PaymentSchedule.status == "upcoming",
            PaymentSchedule.due_date.between(today, today + timedelta(days=2)),
        ).all()
        overdue = PaymentSchedule.query.filter(
            PaymentSchedule.status.in_(["upcoming", "partial"]),
            PaymentSchedule.due_date < today,
        ).all()
        for schedule in upcoming + overdue:
            borrower = schedule.loan.borrower if schedule.loan else None
            if borrower and borrower.email:
                email_type = "payment_reminder"
                try:
                    send_email(email_type, borrower.email, {"borrower_name": borrower.name, "loan_reference": f"Loan #{schedule.loan_id}", "due_date": schedule.due_date.isoformat(), "amount_due": str(schedule.expected_amount)})
                    db.session.add(AuditLog(user_id=schedule.loan.created_by, action="SEND_REMINDER", table_name="payment_schedules", record_id=schedule.id, details=borrower.email))
                except Exception:
                    app.logger.exception("payment reminder failed for schedule %s", schedule.id)
        # Phase 3 item 2: a period counts as missed only when NOTHING at
        # all was paid against it — only 'upcoming' rows qualify, never a
        # 'partial' one (which already has some payment, per item 3). The
        # delay cascades across a whole loan's remaining schedule, so this
        # runs once per affected loan, not once per row.
        missed_loan_ids = {schedule.loan_id for schedule in overdue if schedule.status == "upcoming"}
        for loan_id in missed_loan_ids:
            loan = Loan.query.get(loan_id)
            if loan is not None:
                delay_missed_schedule_periods(loan, today)
        # The other overdue case: a row that's 'partial' (something was
        # paid, but not the full instalment) whose due date has now passed
        # without the shortfall being topped up — give up on the
        # projection and re-amortize the real remaining balance instead.
        partial_loan_ids = {schedule.loan_id for schedule in overdue if schedule.status == "partial"}
        for loan_id in partial_loan_ids:
            loan = Loan.query.get(loan_id)
            if loan is not None:
                carry_over_overdue_partial_periods(loan, today)
        db.session.commit()


def purge_deactivated_users(app):
    """Permanently delete accounts that have been deactivated past the retention window.

    The audit trail is preserved through denormalized actor name/email snapshots
    and ON DELETE SET NULL foreign keys, so history stays readable after the row
    is gone. CEO accounts can never be deactivated in the first place, but the
    role filter here is a defense-in-depth guard against ever deleting one.
    """
    with app.app_context():
        cutoff = datetime.utcnow() - timedelta(days=retention_days())
        candidates = User.query.filter(
            User.is_active.is_(False),
            User.deactivated_at.isnot(None),
            User.deactivated_at <= cutoff,
            User.role != "ceo",
        ).all()
        for user in candidates:
            db.session.add(
                AuditLog(
                    user_id=None,
                    actor_name_snapshot=SYSTEM_ACTOR_NAME,
                    actor_email_snapshot=SYSTEM_ACTOR_EMAIL,
                    action="AUTO_DELETE_USER",
                    table_name="users",
                    record_id=user.id,
                    details=(
                        f"Deactivated on {user.deactivated_at.isoformat()} and permanently deleted "
                        f"after the {retention_days()}-day retention period (name={user.name}, email={user.email})"
                    ),
                )
            )
            db.session.delete(user)
        if candidates:
            db.session.commit()


def backup_dir():
    return os.getenv("BACKUP_DIR", os.path.join(tempfile.gettempdir(), "lms-backups"))


def backup_retention_days():
    try:
        return int(os.getenv("BACKUP_RETENTION_DAYS", "14"))
    except (TypeError, ValueError):
        return 14


def run_nightly_backup(app):
    """Phase 6: an unattended, unencrypted server-side copy (see
    services/backup.py for why no password is used here) kept for
    BACKUP_RETENTION_DAYS (default 14). This protects against local
    disk/database corruption between the CEO's own encrypted downloads —
    it is not a substitute for actually taking a copy off the server,
    which is what the dashboard's staleness warning tracks separately."""
    with app.app_context():
        try:
            filename, size_bytes = write_nightly_backup(
                backup_dir(), app.config["UPLOAD_DIR"], backup_retention_days(),
            )
            db.session.add(BackupLog(kind="nightly", size_bytes=size_bytes, note=filename))
            db.session.commit()
        except Exception:
            app.logger.exception("nightly backup failed")
            db.session.rollback()
            db.session.add(BackupLog(kind="nightly", success=False, note="nightly backup failed — see server log"))
            db.session.commit()


def start_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if not _acquire_scheduler_lock():
        # Another worker process already holds the lock for this container.
        return None
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(lambda: reconcile_reminders(app), "interval", days=1, id="payment-reminders", replace_existing=True)
    _scheduler.add_job(lambda: purge_deactivated_users(app), "interval", days=1, id="purge-deactivated-users", replace_existing=True)
    # A fixed off-peak hour (cron), not "interval, days=1" like the two jobs
    # above — those don't care what time of day they run; a backup should
    # consistently land at a predictable, low-traffic hour.
    _scheduler.add_job(lambda: run_nightly_backup(app), "cron", hour=2, minute=0, id="nightly-backup", replace_existing=True)
    _scheduler.start()
    return _scheduler
