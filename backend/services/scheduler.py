from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from extensions import db
from models import AuditLog, PaymentSchedule
from services.email_client import send_email

_scheduler = None


def reconcile_reminders(app):
    with app.app_context():
        today = date.today()
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
            if schedule in overdue and schedule.status == "upcoming":
                schedule.status = "missed"
        db.session.commit()


def start_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(lambda: reconcile_reminders(app), "interval", days=1, id="payment-reminders", replace_existing=True)
    _scheduler.start()
    return _scheduler
