import os
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request, send_file, send_from_directory
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

import branding
from extensions import db
from models import (
    Asset,
    AssetType,
    Borrower,
    CapitalEntry,
    Employee,
    Expense,
    LeaveRequest,
    Loan,
    LoanProduct,
    PaymentSchedule,
    Penalty,
    Repayment,
)
from routes.auth import auth_required
from services.accounts import send_email_async
from services.approval import NOT_AN_APPROVER, OUT_OF_SCOPE, SELF_APPROVAL, approval_denial
from services.identity_verification import is_configured, normalize_nida, verify_nin
from services.loan_calculator import add_months, amortization_schedule, local_today, money, schedule_totals, whole_up
from services.pdf import schedule_pdf
from services.permissions import has_permission

operations_bp = Blueprint("operations", __name__, url_prefix="/api")


def parse_date(value, field):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be YYYY-MM-DD")


def parse_money(value, field, min_value=Decimal("0")):
    """Shared money validation: rejects missing/non-numeric/negative/fractional
    values with a clear message. Every money amount in this system is a
    WHOLE shilling (Part 1.3) — a fractional amount is REJECTED outright,
    never silently rounded, since it's a direct user entry, not a computed
    figure."""
    if value is None or value == "":
        raise ValueError(f"{field} is required")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError, ArithmeticError):
        raise ValueError(f"{field} must be a valid number")
    if amount != amount.to_integral_value():
        raise ValueError("Enter an amount in whole shillings.")
    if amount < min_value:
        raise ValueError(f"{field} must not be negative")
    return amount


def json_row(row, extra=None):
    data = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    for key, value in list(data.items()):
        if isinstance(value, Decimal):
            data[key] = float(value)
        elif isinstance(value, (date, datetime)):
            data[key] = value.isoformat()
    if extra:
        data.update(extra)
    return data


def audit(user, action, table, record_id, details=None):
    from models import AuditLog
    db.session.add(
        AuditLog(
            user_id=user.id,
            actor_name_snapshot=user.name,
            actor_email_snapshot=user.email,
            action=action,
            table_name=table,
            record_id=record_id,
            details=details,
        )
    )


def error(message, status=400):
    return jsonify({"message": message}), status


def role_required(*roles):
    def decorator(fn):
        @auth_required
        def wrapped(user, *args, **kwargs):
            if user.role not in roles:
                return error("You don't have permission to do this.", 403)
            return fn(user, *args, **kwargs)
        wrapped.__name__ = fn.__name__
        return wrapped
    return decorator


def permission_required(*permissions, any_of=False):
    """The single gate every write endpoint should use: has_permission() is the
    one function that decides yes/no (Part 1.3). any_of=True accepts any one
    of the listed permissions instead of requiring all of them."""
    def decorator(fn):
        @auth_required
        def wrapped(user, *args, **kwargs):
            ok = any(has_permission(user, p) for p in permissions) if any_of else all(
                has_permission(user, p) for p in permissions
            )
            if not ok:
                return error("You don't have permission to do this.", 403)
            return fn(user, *args, **kwargs)
        wrapped.__name__ = fn.__name__
        return wrapped
    return decorator


def approval_denied_response(denial, record):
    """Turn an approval_denial() code into the plain-language 403 the UI shows."""
    if denial == SELF_APPROVAL:
        return error("maker-checker rule prevents self-approval", 403)
    if denial == OUT_OF_SCOPE:
        permission = getattr(record, "approval_permission", "this")
        label = permission.split(":")[0].replace("_", " ") if isinstance(permission, str) else "this"
        return error(f"Your account is not assigned to approve {label}.", 403)
    return error("You don't have permission to do this.", 403)


def can_decide(user, record):
    """Whether this user could approve/reject the record right now (drives UI buttons)."""
    return approval_denial(user, record) is None


def company_rounding_step():
    """The default instalment-rounding step (branding.py) — only used when
    a NEW loan is created; an existing loan always keeps its own
    already-stored rounding_step regardless of later changes here."""
    return branding.DEFAULT_ROUNDING_STEP


def build_schedules(loan, start_date=None, principal=None, term=None):
    rows = amortization_schedule(
        principal if principal is not None else loan.principal_amount,
        loan.interest_rate,
        term if term is not None else loan.term_months,
        start_date or loan.start_date,
        step=loan.rounding_step,
    )
    loan.schedules.clear()
    for row in rows:
        loan.schedules.append(
            PaymentSchedule(
                due_date=row["due_date"],
                # Phase 3 item 2: the plan as originally created — never
                # touched again, even once due_date itself gets pushed back.
                original_due_date=row["due_date"],
                expected_amount=row["payment_amount"],
                original_expected_amount=row["payment_amount"],
                principal_portion=row["principal_portion"],
                interest_portion=row["interest_portion"],
                status="upcoming",
            )
        )


@operations_bp.post("/loan-calculator/preview")
@permission_required("calculator:use")
def calculator_preview(_user):
    data = request.get_json(silent=True) or {}
    if data.get("interest_type", "reducing_balance") != "reducing_balance":
        return error("only reducing_balance is supported")
    try:
        # A start date for the preview too (Part 3) - defaults to today so a
        # due-date column can be shown without forcing the user to pick one.
        start_date = parse_date(data["start_date"], "start_date") if data.get("start_date") else local_today()
        step = int(data["rounding_step"]) if data.get("rounding_step") else company_rounding_step()
        schedule = amortization_schedule(data["principal"], data["interest_rate"], data["term_months"], start_date, step=step)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return error(str(exc))
    # Same shared computation the loan detail page, schedule PDF and borrower
    # statement use — never a separate calculation per screen (Part: schedule totals).
    totals = {
        key: float(value)
        for key, value in schedule_totals(
            (row["principal_portion"], row["interest_portion"], row["payment_amount"]) for row in schedule
        ).items()
    }
    for row in schedule:
        row["due_date"] = row["due_date"].isoformat() if row["due_date"] else None
        for key, value in row.items():
            if isinstance(value, Decimal):
                row[key] = float(value)
    return jsonify({"schedule": schedule, "totals": totals})


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
IMAGE_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
BORROWER_FILE_FIELDS = {"photo": "photo_path", "id-document": "id_document_path"}
ID_TYPES = ("nida", "driving_licence", "voter_id", "passport", "other")


def validated_upload(file_storage, label):
    """Read an uploaded borrower photo / ID document, returning (bytes, extension).

    Accepts an image (JPEG/PNG/WebP, decoded with Pillow) or a PDF (parsed
    with pypdf) — an ID document is very often a scanned PDF, not a photo
    (Part 3.1). Content is decoded/parsed rather than trusting the client's
    file name or Content-Type, so a renamed script or oversized file is
    rejected either way.
    """
    from io import BytesIO

    data = file_storage.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise ValueError(f"{label} is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"{label} must be 5 MB or smaller")

    if data.lstrip()[:5] == b"%PDF-":
        from pypdf import PdfReader

        try:
            reader = PdfReader(BytesIO(data))
            if len(reader.pages) < 1:
                raise ValueError("empty PDF")
        except Exception:
            raise ValueError(f"{label} must be a valid JPEG, PNG, WebP image, or PDF")
        return data, "pdf"

    from PIL import Image

    try:
        image = Image.open(BytesIO(data))
        image_format = image.format
        image.verify()
    except Exception:
        raise ValueError(f"{label} must be a valid JPEG, PNG, WebP image, or PDF")
    if image_format not in IMAGE_EXTENSIONS:
        raise ValueError(f"{label} must be a valid JPEG, PNG, WebP image, or PDF")
    return data, IMAGE_EXTENSIONS[image_format]


def borrower_folder(borrower_id):
    return os.path.join(current_app.config["UPLOAD_DIR"], "borrowers", str(borrower_id))


def store_borrower_file(borrower, kind, data, extension):
    """Write an upload under a generated name and point the borrower at it."""
    folder = borrower_folder(borrower.id)
    os.makedirs(folder, exist_ok=True)
    name = f"{kind}-{uuid.uuid4().hex}.{extension}"
    with open(os.path.join(folder, name), "wb") as handle:
        handle.write(data)
    column = BORROWER_FILE_FIELDS[kind]
    previous = getattr(borrower, column)
    setattr(borrower, column, name)
    return previous


def remove_borrower_file(borrower_id, name):
    if name:
        try:
            os.remove(os.path.join(borrower_folder(borrower_id), name))
        except OSError:
            pass


def borrower_json(borrower):
    """Borrower fields for the API. Stored file names never leave the server."""
    data = json_row(borrower)
    data.pop("photo_path", None)
    data.pop("id_document_path", None)
    data["has_photo"] = bool(borrower.photo_path)
    data["has_id_document"] = bool(borrower.id_document_path)
    # Part 6.2: the verification UI only shows when a provider is actually
    # configured - never a permanent "not configured" message.
    data["id_verification_configured"] = is_configured()
    return data


@operations_bp.post("/borrowers")
@permission_required("borrowers:manage")
def create_borrower(user):
    # JSON (no files) and multipart/form-data (with photo / ID document) are both accepted.
    multipart = (request.mimetype or "").startswith("multipart/")
    data = request.form if multipart else (request.get_json(silent=True) or {})
    required = ["name", "phone", "id_number"]
    if any(not str(data.get(field) or "").strip() for field in required):
        return error("name, phone, and id_number are required")

    id_type = (data.get("id_type") or "nida").strip().lower()
    if id_type not in ID_TYPES:
        return error(f"id_type must be one of: {', '.join(ID_TYPES)}")
    id_number = str(data["id_number"]).strip()
    warning = None
    if id_type == "nida":
        id_number = normalize_nida(id_number)
        if len(id_number) != 20:
            # Soft warning only — the real NIDA format has not been confirmed
            # against physical cards yet, so this never blocks saving (Part 3.2).
            warning = f"NIDA numbers are usually 20 digits; this one has {len(id_number)}. Double-check it before saving."

    existing = Borrower.query.filter_by(id_type=id_type, id_number=id_number).first()
    if existing:
        return jsonify({
            "message": f"A borrower with this {id_type.replace('_', ' ')} number already exists.",
            "existing_borrower_id": existing.id,
            "existing_borrower_name": existing.name,
        }), 409

    uploads = {}
    if multipart:
        try:
            for kind, label in (("photo", "Profile photo"), ("id-document", "ID document image")):
                file = request.files.get(kind.replace("-", "_"))
                if file and file.filename:
                    uploads[kind] = validated_upload(file, label)
        except ValueError as exc:
            return error(str(exc))

    borrower = Borrower(
        name=data["name"].strip(), phone=data["phone"].strip(),
        id_type=id_type, id_number=id_number,
        email=(data.get("email") or None), address=data.get("address"),
    )
    db.session.add(borrower)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return error("this ID number is already registered", 409)
    for kind, (content, extension) in uploads.items():
        store_borrower_file(borrower, kind, content, extension)
    audit(user, "CREATE", "borrowers", borrower.id)
    db.session.commit()
    body = {"borrower": borrower_json(borrower)}
    if warning:
        body["warning"] = warning
    return jsonify(body), 201


@operations_bp.put("/borrowers/<int:borrower_id>")
@permission_required("borrowers:manage")
def update_borrower(user, borrower_id):
    borrower = Borrower.query.get_or_404(borrower_id)
    data = request.get_json(silent=True) or {}
    try:
        for field in ("name", "phone", "email", "address"):
            if field in data:
                setattr(borrower, field, (data[field] or None) if field in ("email", "address") else str(data[field]).strip())
        if "id_type" in data or "id_number" in data:
            id_type = (data.get("id_type") or borrower.id_type).strip().lower()
            id_number = str(data.get("id_number") or borrower.id_number).strip()
            if id_type not in ID_TYPES:
                raise ValueError(f"id_type must be one of: {', '.join(ID_TYPES)}")
            if id_type == "nida":
                id_number = normalize_nida(id_number)
            borrower.id_type, borrower.id_number = id_type, id_number
            borrower.id_verified = False
            borrower.id_verified_at = None
    except (TypeError, ValueError) as exc:
        return error(str(exc))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("this ID number is already registered", 409)
    return jsonify({"borrower": borrower_json(borrower)})


@operations_bp.post("/borrowers/<int:borrower_id>/verify-id")
@permission_required("borrowers:manage")
def verify_borrower_id(user, borrower_id):
    """Seam for a real NIDA/KYC provider — today always reports not_configured
    (services/identity_verification.py), never a false positive (Part 3.4)."""
    borrower = Borrower.query.get_or_404(borrower_id)
    result = verify_nin(borrower.id_number, borrower.id_type)
    if result.get("status") == "verified":
        borrower.id_verified = True
        borrower.id_verified_at = datetime.utcnow()
        borrower.id_verification_source = result.get("source", "unknown")
        audit(user, "VERIFY_ID", "borrowers", borrower.id)
        db.session.commit()
    return jsonify({"result": result, "borrower": borrower_json(borrower)})


@operations_bp.post("/borrowers/<int:borrower_id>/<kind>")
@permission_required("borrowers:manage")
def upload_borrower_file(user, borrower_id, kind):
    if kind not in BORROWER_FILE_FIELDS:
        return error("not found", 404)
    borrower = Borrower.query.get_or_404(borrower_id)
    file = request.files.get("file")
    if not file or not file.filename:
        return error("choose an image file to upload")
    try:
        content, extension = validated_upload(file, "Profile photo" if kind == "photo" else "ID document image")
    except ValueError as exc:
        return error(str(exc))
    previous = store_borrower_file(borrower, kind, content, extension)
    audit(user, "UPLOAD_" + kind.replace("-", "_").upper(), "borrowers", borrower.id)
    db.session.commit()
    remove_borrower_file(borrower.id, previous)
    return jsonify({"borrower": borrower_json(borrower)})


@operations_bp.get("/borrowers/<int:borrower_id>/<kind>")
@permission_required("borrowers:view", "borrowers:manage", any_of=True)
def download_borrower_file(user, borrower_id, kind):
    """Authenticated file serving: uploads are never exposed as static
    files. Phase 2 item 9 (F-31): this was @auth_required only — ANY
    logged-in account, including an HR or Finance department_manager with
    no business reason to see a loan borrower's photo or ID document, could
    download it. Now gated behind the same borrowers:view/borrowers:manage
    permission the rest of the borrowers module uses, and every download
    is written to the audit trail."""
    if kind not in BORROWER_FILE_FIELDS:
        return error("not found", 404)
    borrower = Borrower.query.get_or_404(borrower_id)
    name = getattr(borrower, BORROWER_FILE_FIELDS[kind])
    if not name:
        return error("no file uploaded", 404)
    audit(user, "DOWNLOAD_" + kind.replace("-", "_").upper(), "borrowers", borrower.id)
    db.session.commit()
    response = send_from_directory(borrower_folder(borrower.id), name, max_age=0)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def optional_int(value, field):
    """Optional whole-number limit: blank/None means 'no restriction'."""
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a whole number")
    if number < 1:
        raise ValueError(f"{field} must be at least 1")
    return number


def optional_money(value, field):
    if value is None or value == "":
        return None
    return parse_money(value, field)


def product_limits(data, current=None):
    """Parse the four optional limits, validating min <= max when both are set."""
    limits = {}
    for field, parser in (
        ("min_term_months", optional_int), ("max_term_months", optional_int),
        ("min_amount", optional_money), ("max_amount", optional_money),
    ):
        if field in data:
            limits[field] = parser(data[field], field)
        else:
            limits[field] = getattr(current, field, None) if current else None
    for low, high in (("min_term_months", "max_term_months"), ("min_amount", "max_amount")):
        if limits[low] is not None and limits[high] is not None and limits[low] > limits[high]:
            raise ValueError(f"{low} must not be greater than {high}")
    return limits


@operations_bp.post("/loan-products")
@permission_required("loan_products:manage")
def create_product(user):
    data = request.get_json(silent=True) or {}
    try:
        term = int(data["default_term_months"]) if "default_term_months" in data else 12
        if term < 1:
            raise ValueError("default_term_months must be at least 1")
        product = LoanProduct(
            name=data["name"], default_interest_rate=data["default_interest_rate"],
            default_term_months=term, is_active=True, **product_limits(data),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return error(str(exc))
    db.session.add(product)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("a loan product with this name already exists", 409)
    return jsonify({"loan_product": json_row(product)}), 201


@operations_bp.put("/loan-products/<int:product_id>")
@permission_required("loan_products:manage")
def update_product(user, product_id):
    product = LoanProduct.query.get_or_404(product_id)
    data = request.get_json(silent=True) or {}
    try:
        limits = product_limits(data, current=product)
        for field in ("name", "default_interest_rate", "is_active"):
            if field in data:
                setattr(product, field, data[field])
        if "default_term_months" in data:
            term = int(data["default_term_months"])
            if term < 1:
                raise ValueError("default_term_months must be at least 1")
            product.default_term_months = term
        for field, value in limits.items():
            setattr(product, field, value)
    except (TypeError, ValueError) as exc:
        return error(str(exc))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("a loan product with this name already exists", 409)
    return jsonify({"loan_product": json_row(product)})


@operations_bp.post("/loans")
@permission_required("loans:create")
def create_loan(user):
    """A loan product is now OPTIONAL ("Negotiated rate" — Part 2.2): no
    product -> the Maker sets principal/rate/term directly. EITHER way this
    builds the exact same Loan row and runs through the exact same
    loan_calculator.py function (build_schedules) below — nothing forks.

    When a product IS selected, ONLY its rate is LOCKED server-side (Part
    2.1): whatever the client sends for interest_rate is ignored outright in
    favor of the product's own rate. The TERM IS NEVER LOCKED — it is always
    entered per loan, same as a negotiated loan, and is only checked against
    the product's own optional min/max term as validation bounds (this was a
    bug: term used to be force-set to the product's default_term_months,
    with no way to pick anything else).
    """
    data = request.get_json(silent=True) or {}
    try:
        start_date = parse_date(data["start_date"], "start_date")
        borrower = Borrower.query.get(int(data["borrower_id"]))
        if not borrower:
            return error("borrower not found", 404)
        principal = parse_money(data.get("principal_amount"), "principal_amount", min_value=Decimal("1"))

        product_id = data.get("loan_product_id")
        product = LoanProduct.query.get(int(product_id)) if product_id not in (None, "") else None
        if product_id not in (None, "") and product is None:
            return error("loan product not found", 404)

        term = int(data["term_months"])
        if term < 1:
            return error("term_months must be at least 1")

        if product is not None:
            # Rate ONLY is locked to the product — never the client's own rate.
            rate = Decimal(str(product.default_interest_rate))
            if product.min_term_months is not None and term < product.min_term_months:
                return error(f"term_months must be at least {product.min_term_months} for this product")
            if product.max_term_months is not None and term > product.max_term_months:
                return error(f"term_months must be at most {product.max_term_months} for this product")
        else:
            rate = Decimal(str(data["interest_rate"]))
            if rate < 0:
                return error("interest_rate must not be negative")

        if product is not None:
            # A limit that is not set on the product is simply not enforced.
            if product.min_amount is not None and principal < product.min_amount:
                return error("principal is outside product limits")
            if product.max_amount is not None and principal > product.max_amount:
                return error("principal is outside product limits")
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return error(str(exc))
    loan = Loan(
        borrower_id=borrower.id, loan_product_id=product.id if product else None, principal_amount=principal,
        interest_rate=rate, term_months=term, start_date=start_date, status="pending_approval",
        outstanding_balance=principal, created_by=user.id, creator_name_snapshot=user.name,
        rounding_step=company_rounding_step(),
    )
    db.session.add(loan)
    db.session.flush()
    build_schedules(loan)
    audit(user, "CREATE", "loans", loan.id)
    db.session.commit()
    return jsonify({"loan": json_row(loan)}), 201


OPEN_SCHEDULE_STATUSES = ("upcoming", "partial", "missed")


def settlement_amount(loan):
    """What it takes to clear the loan today: principal outstanding plus the
    interest due on the instalment currently open."""
    open_rows = [row for row in sorted(loan.schedules, key=lambda r: r.due_date) if row.status in OPEN_SCHEDULE_STATUSES]
    interest_due = money(open_rows[0].interest_portion) if open_rows else Decimal("0")
    return money(money(loan.outstanding_balance) + interest_due)


def apply_repayment(loan, amount, payment_date):
    """Allocate a payment and reconcile the rest of the schedule.

    Schedule = plan, repayments = reality, balance always derived from reality:
    interest due on the earliest open instalment is settled first, the rest
    reduces principal, and the instalments still to come are re-amortized with
    the SAME EMI function (services.loan_calculator.amortization_schedule) on
    what is actually still owed, over the periods actually remaining.

    Interest due for the currently-open period is always computed FRESH
    from the loan's actual outstanding principal at the start of that
    period (balance x monthly rate, rounded up) — never read from a
    possibly-stale stored row.interest_portion, which can drift out of
    sync with the real balance (e.g. a penalty directly adjusts
    outstanding_balance without rebuilding the schedule).

    A row only closes ('paid') once a payment covers what is CURRENTLY due
    on it in full (interest first, then principal) — anything less leaves
    it open ('partial'), its own interest/principal reduced to the residual
    still owed, as a PROJECTION assuming the remainder is paid by the due
    date (later rows are re-amortized on that assumption too). This is a
    per-row running balance: a row partially paid once and then topped up
    before its due date closes correctly and the projection is simply
    confirmed, unchanged. If the due date passes with the shortfall still
    unpaid, carry_over_overdue_partial_periods() below (called by the same
    daily job that handles missed months) gives up on the projection and
    re-amortizes the real remaining balance instead — never this function,
    which only ever sees "today's" payment in isolation.

    Returns (schedule_row_or_None, interest_paid, principal_paid).
    """
    balance = money(loan.outstanding_balance)
    open_rows = [row for row in sorted(loan.schedules, key=lambda r: r.due_date) if row.status in OPEN_SCHEDULE_STATUSES]
    row = open_rows[0] if open_rows else None

    # The row's own interest_portion IS "monthly rate x the actual
    # outstanding principal at the start of the period" — kept correct by
    # construction (the last rebuild always derived it from the real
    # balance at that time) and trusted here as-is, since it may ALSO have
    # been deliberately adjusted for a legitimate reason this function must
    # not second-guess (a settlement discount reduces it directly before
    # calling this). The one case where it could otherwise go stale —
    # something OTHER than a repayment changing outstanding_balance
    # directly (a penalty approved/reversed) — is handled at the source by
    # resync_open_row_interest() below, called right where that happens,
    # not here.
    interest_due = money(row.interest_portion) if row else Decimal("0")
    # What is currently due on this row as a whole (interest + principal) —
    # the bar a payment must clear to close it. For a row that has already
    # been partially paid before, this is the RESIDUAL still owed, not the
    # original instalment.
    due_on_row = money(row.expected_amount) if row else Decimal("0")
    interest_paid = min(amount, interest_due)
    principal_paid = min(amount - interest_paid, balance)
    new_balance = money(balance - principal_paid)
    loan.outstanding_balance = new_balance

    later_rows = open_rows[1:]
    owed_on_row = Decimal("0")  # principal still due on a part-paid instalment (projection path only)

    if row is not None:
        if amount >= due_on_row:
            row.status = "paid"
        else:
            # Part-paid: the instalment stays open for what is still owed on it.
            row.interest_portion = money(money(row.interest_portion) - interest_paid)
            row.principal_portion = money(max(money(row.principal_portion) - principal_paid, Decimal("0")))
            row.expected_amount = money(row.interest_portion + row.principal_portion)
            row.status = "partial"
            owed_on_row = money(row.principal_portion)

    if new_balance == 0:
        # Fully repaid: the plan is over, so drop the unpaid future instalments
        # rather than leave 'upcoming' rows that would keep triggering reminders.
        loan.status = "closed"
        if row is not None:
            row.status = "paid"
        for future in later_rows:
            loan.schedules.remove(future)
            db.session.delete(future)
    else:
        rest = new_balance - owed_on_row
        if later_rows and rest > 0:
            projected = amortization_schedule(rest, loan.interest_rate, len(later_rows), step=loan.rounding_step)
            for entry, projection in zip(later_rows, projected):
                entry.expected_amount = projection["payment_amount"]
                entry.principal_portion = projection["principal_portion"]
                entry.interest_portion = projection["interest_portion"]
        elif not later_rows and rest > 0:
            # The balance outlived the schedule (e.g. an approved penalty after
            # the last instalment): add a final instalment so it is never left
            # active with nothing scheduled.
            last_due = row.due_date if row else payment_date
            tail = amortization_schedule(rest, loan.interest_rate, 1, last_due, step=loan.rounding_step)[0]
            loan.schedules.append(
                PaymentSchedule(
                    due_date=tail["due_date"], original_due_date=tail["due_date"],
                    expected_amount=tail["payment_amount"],
                    original_expected_amount=tail["payment_amount"],
                    principal_portion=tail["principal_portion"], interest_portion=tail["interest_portion"],
                    status="upcoming",
                )
            )

    if row is not None and row.status == "paid":
        # PART 1 (critical): a row that is now paid must show what was
        # actually paid against it - the real repayment split - never the
        # original/stale scheduled figures. This matters most when `amount`
        # is larger than the instalment that was due: the extra also lands
        # on this row as principal_paid, so without this the row would
        # under-report principal and the totals row would no longer
        # reconcile to the loan's original principal.
        #
        # A row can be settled by MORE THAN ONE repayment (one or more
        # partial payments, then a final one that clears it) - the row must
        # show the CUMULATIVE interest/principal across every repayment ever
        # applied to it, not just this last transaction's amount, or the
        # earlier partial payment's contribution silently disappears from
        # the row (and therefore from the totals row too). Prior repayments
        # against this exact row are already committed; this transaction's
        # own repayment record is added by the caller right after this call.
        prior = Repayment.query.filter_by(schedule_id=row.id).all()
        row.interest_portion = money(sum((Decimal(str(r.interest_portion)) for r in prior), Decimal(0)) + interest_paid)
        row.principal_portion = money(sum((Decimal(str(r.principal_portion)) for r in prior), Decimal(0)) + principal_paid)
        # Phase 3 item 4: this is the row's CUMULATIVE "payment received"
        # (principal + interest across every repayment ever applied to it)
        # — a second, immediately-following assignment here used to
        # overwrite it with just THIS transaction's amount, silently
        # dropping any earlier partial payment's contribution. Fixed by
        # simply not doing that second assignment.
        row.expected_amount = money(row.interest_portion + row.principal_portion)

    return row, interest_paid, principal_paid


def resync_open_row_interest(loan):
    """Phase 3 item 1: "interest each period = monthly rate x the ACTUAL
    outstanding principal at the start of that period" — kept true even
    when something other than a repayment changes outstanding_balance
    directly (a penalty approved or reversed), by refreshing the current
    open period's interest right here, at the source, rather than inside
    apply_repayment() (which must trust row.interest_portion as-is, since
    it can also have been deliberately adjusted for other legitimate
    reasons, e.g. a settlement discount).

    Only ever touches a row that hasn't been partially paid yet
    ('upcoming') — a 'partial' row's interest_portion is a RESIDUAL (what
    is still owed after an earlier insufficient payment), never a fresh
    balance-based figure, and item 3 leaves that path untouched."""
    open_rows = sorted((r for r in loan.schedules if r.status == "upcoming"), key=lambda r: r.due_date)
    if not open_rows:
        return
    row = open_rows[0]
    monthly_rate = Decimal(str(loan.interest_rate)) / Decimal(100)
    new_interest = whole_up(money(loan.outstanding_balance) * monthly_rate)
    delta = new_interest - money(row.interest_portion)
    if delta == 0:
        return
    row.interest_portion = new_interest
    row.expected_amount = money(row.expected_amount + delta)


def delay_missed_schedule_periods(loan, today=None):
    """Phase 3 item 2: a period counts as missed only when its due date has
    passed with NO payment at all against it — status == 'upcoming' only;
    a 'partial' row (item 3's kept-as-is case) already has SOME payment,
    so it is never 'missed'. Nothing about the money changes: balance,
    instalment amounts and total interest are untouched here — every
    unpaid due date (the missed one and every open one after it) simply
    moves one month later, cascading. original_due_date is set once (at
    row creation, in build_schedules()/apply_repayment()'s tail-row branch)
    and never overwritten here, so reporting can always tell how far
    behind the ORIGINAL plan a loan is, no matter how many times its
    schedule has since been pushed back.

    Idempotent: called by the daily job every day, but a given period only
    ever shifts once per time it is genuinely overdue — after shifting,
    its new due_date is in the future, so the `while` loop's own check
    stops it from shifting again until that new date ALSO passes unpaid
    (running the job twice the same day is a no-op the second time). A
    loan that fell behind by more than one period before the job ran
    catches up one shift at a time, in this same call.

    Returns the list of PaymentSchedule rows that were shifted (possibly
    empty, if nothing is newly overdue).
    """
    today = today or local_today()
    shifted = []
    while True:
        open_rows = sorted((row for row in loan.schedules if row.status == "upcoming"), key=lambda row: row.due_date)
        if not open_rows or open_rows[0].due_date > today:
            break
        for row in open_rows:
            if row.original_due_date is None:
                row.original_due_date = row.due_date
            row.due_date = add_months(row.due_date, 1)
            row.delayed_months = (row.delayed_months or 0) + 1
            shifted.append(row)
    return shifted


def carry_over_overdue_partial_periods(loan, today=None):
    """The other half of the partial-payment story: apply_repayment()
    treats a part-paid row's later_rows projection as provisional, assuming
    the shortfall gets topped up by the row's own due date. Called by the
    SAME daily job as delay_missed_schedule_periods() above, this is what
    actually settles that assumption once the due date passes — reusing
    the SAME amortization_schedule() calculator, never a second one.

    If the due date has passed and the row is still 'partial' (the
    shortfall was never topped up): lock the row in at what was ACTUALLY
    received (status 'paid', flagged paid_less_than_scheduled — display
    only, same as a row closed for less than scheduled any other way),
    and re-amortize the real remaining balance over the real remaining
    periods — releasing the shortfall that was reserved on this row back
    into the pool, since it is never coming.

    Idempotent: once carried over the row is 'paid', so a second run the
    same day (or any day after) finds nothing left to do.
    """
    today = today or local_today()
    open_rows = sorted((row for row in loan.schedules if row.status in OPEN_SCHEDULE_STATUSES), key=lambda row: row.due_date)
    if not open_rows:
        return None
    row = open_rows[0]
    if row.status != "partial" or row.due_date >= today:
        return None

    later_rows = open_rows[1:]
    prior = Repayment.query.filter_by(schedule_id=row.id).all()
    row.interest_portion = money(sum((Decimal(str(r.interest_portion)) for r in prior), Decimal(0)))
    row.principal_portion = money(sum((Decimal(str(r.principal_portion)) for r in prior), Decimal(0)))
    row.expected_amount = money(row.interest_portion + row.principal_portion)
    row.status = "paid"
    row.paid_less_than_scheduled = True

    rest = money(loan.outstanding_balance)
    if later_rows and rest > 0:
        projected = amortization_schedule(rest, loan.interest_rate, len(later_rows), step=loan.rounding_step)
        for entry, projection in zip(later_rows, projected):
            entry.expected_amount = projection["payment_amount"]
            entry.principal_portion = projection["principal_portion"]
            entry.interest_portion = projection["interest_portion"]
    elif not later_rows and rest > 0:
        tail = amortization_schedule(rest, loan.interest_rate, 1, row.due_date, step=loan.rounding_step)[0]
        loan.schedules.append(
            PaymentSchedule(
                due_date=tail["due_date"], original_due_date=tail["due_date"],
                expected_amount=tail["payment_amount"], original_expected_amount=tail["payment_amount"],
                principal_portion=tail["principal_portion"], interest_portion=tail["interest_portion"],
                status="upcoming",
            )
        )
    elif rest <= 0:
        loan.status = "closed"
    return row


def idempotency_key_from(data):
    """Phase 2 item 5: the repayment/settle forms send a client-generated
    key, one per form submission — a retried/double-fired request resends
    the SAME key, so it's recognized as a replay instead of a second
    payment. Optional (None if absent) so a caller that doesn't supply one
    behaves exactly as before this existed; the frontend always sends one."""
    key = (data.get("idempotency_key") or "").strip()
    if not key:
        return None
    if len(key) > 64:
        raise ValueError("idempotency_key must be 64 characters or fewer")
    return key


def replayed_repayment_response(existing):
    return jsonify({
        "repayment": json_row(existing), "loan": json_row(existing.loan), "replay": True,
    }), 200


@operations_bp.post("/repayments")
@permission_required("repayments:record")
def create_repayment(user):
    data = request.get_json(silent=True) or {}
    try:
        loan_id = int(data["loan_id"])
        amount = parse_money(data.get("amount_paid"), "amount_paid", min_value=Decimal("1"))
        payment_date = parse_date(data["payment_date"], "payment_date")
        idempotency_key = idempotency_key_from(data)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return error(str(exc))
    existing = Repayment.query.filter_by(idempotency_key=idempotency_key).first() if idempotency_key else None
    if existing is not None:
        return replayed_repayment_response(existing)
    # Phase 2 item 4: locked (SELECT ... FOR UPDATE) so two concurrent
    # repayments against the same loan serialize instead of both computing
    # their allocation against the same stale outstanding_balance.
    loan = Loan.query.filter_by(id=loan_id).with_for_update().first()
    if not loan:
        return error("loan not found", 404)
    if loan.status != "active":
        return error("repayments can only be recorded against an active loan")
    if amount > settlement_amount(loan):
        return error(f"The most you can pay today to settle this loan is {settlement_amount(loan):,.0f}.")

    try:
        # Phase 2 item 4: the flush() below can itself raise StaleDataError
        # (it's what actually issues the UPDATE), so the guard starts here,
        # not just around the later explicit commit().
        schedule, interest_paid, principal_paid = apply_repayment(loan, amount, payment_date)
        repayment = Repayment(
            loan_id=loan.id, schedule_id=schedule.id if schedule else None, amount_paid=amount,
            payment_date=payment_date, principal_portion=principal_paid,
            interest_portion=interest_paid, balance_after=loan.outstanding_balance,
            idempotency_key=idempotency_key,
        )
        db.session.add(repayment)
        db.session.flush()
        audit(user, "CREATE", "repayments", repayment.id, f"loan_id={loan.id}")
        db.session.commit()
    except StaleDataError:
        db.session.rollback()
        return retry_conflict_response()
    except IntegrityError:
        # Phase 2 item 5: a genuinely concurrent (not sequential) retry with
        # the SAME key raced past the existing-row check above; the unique
        # constraint caught it instead — return the row the other request
        # just committed rather than erroring.
        db.session.rollback()
        existing = Repayment.query.filter_by(idempotency_key=idempotency_key).first() if idempotency_key else None
        if existing is not None:
            return replayed_repayment_response(existing)
        return error("this payment could not be recorded — please try again", 409)
    if loan.borrower and loan.borrower.email:
        send_email_async("payment_received", loan.borrower.email, {"borrower_name": loan.borrower.name, "loan_reference": f"Loan #{loan.id}", "amount_paid": str(amount), "balance_remaining": str(loan.outstanding_balance), "payment_date": payment_date.isoformat()})
    return jsonify({"repayment": json_row(repayment), "loan": json_row(loan)}), 201


@operations_bp.post("/loans/<int:loan_id>/settle")
@permission_required("repayments:record")
def settle_loan(user, loan_id):
    """Early full settlement (Part 4). The rule itself is unchanged:
    settlement = outstanding principal + the full interest for the current
    period. The only new piece is an OPTIONAL discount — Loans Manager/
    Head Manager/CEO only, never a Maker or Checker (settlement:discount is
    mapped to the "loans" module, so a Finance/HR manager never has it
    either) — anywhere from 0 up to the full amount needed to settle (not
    capped at the period's interest: a big enough discount also forgives
    some principal, not just interest), with a required reason, written to
    the audit trail. The discount is applied to the schedule/balance
    BEFORE the one shared apply_repayment() path runs, so there is still
    exactly one repayment-reconciliation calculation in the system.
    """
    data = request.get_json(silent=True) or {}
    try:
        idempotency_key = idempotency_key_from(data)
    except ValueError as exc:
        return error(str(exc))
    existing = Repayment.query.filter_by(idempotency_key=idempotency_key).first() if idempotency_key else None
    if existing is not None:
        return replayed_repayment_response(existing)
    # Phase 2 item 4: locked (SELECT ... FOR UPDATE) — same reason as
    # create_repayment() above; a settle and a regular repayment against the
    # same loan must also serialize against each other.
    loan = Loan.query.filter_by(id=loan_id).with_for_update().first()
    if loan is None:
        return error("not found", 404)
    if loan.status != "active":
        return error("repayments can only be recorded against an active loan")

    open_rows = [row for row in sorted(loan.schedules, key=lambda r: r.due_date) if row.status in OPEN_SCHEDULE_STATUSES]
    current_row = open_rows[0] if open_rows else None
    principal = money(loan.outstanding_balance)
    interest_due = money(current_row.interest_portion) if current_row else Decimal("0")

    discount = Decimal("0")
    reason = None
    if data.get("discount") not in (None, "", 0, "0"):
        if not has_permission(user, "settlement:discount"):
            return error("You don't have permission to apply a settlement discount.", 403)
        try:
            discount = parse_money(data.get("discount"), "discount")
        except ValueError as exc:
            return error(str(exc))
        reason = (data.get("discount_reason") or "").strip()
        if not reason:
            return error("A reason is required to apply a settlement discount.")
        if discount > principal + interest_due:
            return error("The discount cannot exceed the total amount needed to settle.")

    total_to_settle = money(principal + interest_due - discount)
    try:
        payment_date = parse_date(data["payment_date"], "payment_date") if data.get("payment_date") else local_today()
    except ValueError as exc:
        return error(str(exc))

    if discount > 0 and current_row is not None:
        # A discount can now exceed the period's interest — anything
        # beyond the available interest also forgives principal, not just
        # interest. Interest is waived on the row itself; any excess is
        # waived by reducing the loan's actual outstanding balance BEFORE
        # settling, so apply_repayment()'s own principal math (and the
        # balance landing at exactly zero) stays consistent.
        interest_waiver = min(discount, current_row.interest_portion)
        principal_waiver = discount - interest_waiver
        current_row.interest_portion = money(current_row.interest_portion - interest_waiver)
        current_row.expected_amount = money(current_row.expected_amount - discount)
        if principal_waiver > 0:
            loan.outstanding_balance = money(loan.outstanding_balance - principal_waiver)

    try:
        # Phase 2 item 4: see create_repayment()'s comment — flush() itself
        # can raise StaleDataError, so the guard starts before it.
        schedule, interest_paid, principal_paid = apply_repayment(loan, total_to_settle, payment_date)
        repayment = Repayment(
            loan_id=loan.id, schedule_id=schedule.id if schedule else None, amount_paid=total_to_settle,
            payment_date=payment_date, principal_portion=principal_paid,
            interest_portion=interest_paid, balance_after=loan.outstanding_balance,
            idempotency_key=idempotency_key,
        )
        db.session.add(repayment)
        db.session.flush()
        audit(user, "CREATE", "repayments", repayment.id, f"loan_id={loan.id} (settlement)")
        if discount > 0:
            audit(
                user, "SETTLEMENT_DISCOUNT", "loans", loan.id,
                f"principal={principal} interest={interest_due} discount={discount} total={total_to_settle} reason={reason}",
            )
        db.session.commit()
    except StaleDataError:
        db.session.rollback()
        return retry_conflict_response()
    except IntegrityError:
        db.session.rollback()
        existing = Repayment.query.filter_by(idempotency_key=idempotency_key).first() if idempotency_key else None
        if existing is not None:
            return replayed_repayment_response(existing)
        return error("this settlement could not be recorded — please try again", 409)
    if loan.borrower and loan.borrower.email:
        send_email_async("payment_received", loan.borrower.email, {"borrower_name": loan.borrower.name, "loan_reference": f"Loan #{loan.id}", "amount_paid": str(total_to_settle), "balance_remaining": str(loan.outstanding_balance), "payment_date": payment_date.isoformat()})
    return jsonify({
        "repayment": json_row(repayment), "loan": json_row(loan),
        "breakdown": {
            "principal": float(principal), "interest": float(interest_due),
            "discount": float(discount), "total_to_settle": float(total_to_settle),
        },
    }), 201


@operations_bp.post("/penalties")
@permission_required("penalties:create")
def create_penalty(user):
    data = request.get_json(silent=True) or {}
    loan = Loan.query.get(data.get("loan_id"))
    if not loan or not data.get("reason"):
        return error("loan_id and reason are required")
    if loan.status != "active":
        return error("penalties can only be added to an active loan")
    try:
        amount = parse_money(data.get("amount"), "amount", min_value=Decimal("0.01"))
    except ValueError as exc:
        return error(str(exc))
    penalty = Penalty(loan_id=loan.id, amount=amount, reason=data["reason"], date_applied=local_today(), added_by=user.id, added_by_name_snapshot=user.name, status="pending")
    db.session.add(penalty)
    db.session.flush()
    audit(user, "CREATE", "penalties", penalty.id)
    db.session.commit()
    return jsonify({"penalty": json_row(penalty)}), 201


@operations_bp.get("/expenses")
@permission_required("expenses:manage")
def list_expenses_ops(user):
    # Kept for symmetry with other modules; routes/resources.py serves the
    # main listing used by the frontend.
    rows = [json_row(row, {"created_by_name": row.added_by_name_snapshot}) for row in Expense.query.order_by(Expense.id.desc()).all()]
    return jsonify({"expenses": rows})


@operations_bp.post("/expenses")
@permission_required("expenses:manage")
def create_expense(user):
    """Recorded directly — no approval workflow (Part 1.1)."""
    data = request.get_json(silent=True) or {}
    try:
        expense = Expense(
            description=data["description"], category=data["category"],
            amount=parse_money(data.get("amount"), "amount", min_value=Decimal("0.01")),
            date=parse_date(data.get("date", data.get("expense_date")), "date"),
            added_by=user.id, added_by_name_snapshot=user.name, status="recorded",
        )
    except (KeyError, TypeError, ValueError) as exc:
        return error(str(exc))
    db.session.add(expense)
    db.session.flush()
    audit(user, "CREATE", "expenses", expense.id)
    db.session.commit()
    return jsonify({"expense": json_row(expense)}), 201


@operations_bp.put("/expenses/<int:expense_id>")
@permission_required("expenses:manage")
def update_expense(user, expense_id):
    expense = Expense.query.get_or_404(expense_id)
    data = request.get_json(silent=True) or {}
    try:
        if "description" in data:
            expense.description = data["description"]
        if "category" in data:
            expense.category = data["category"]
        if "amount" in data:
            expense.amount = parse_money(data["amount"], "amount", min_value=Decimal("0.01"))
        if "date" in data:
            expense.date = parse_date(data["date"], "date")
    except (TypeError, ValueError) as exc:
        return error(str(exc))
    audit(user, "UPDATE", "expenses", expense.id)
    db.session.commit()
    return jsonify({"expense": json_row(expense)})


PENDING_STATUSES = ("pending", "pending_approval")


def retry_conflict_response():
    """Phase 2 item 4: a lock_version conflict that is NOT the same record
    being decided twice (e.g. two penalties on the same loan both touching
    its outstanding_balance, or two repayments on the same loan) — there is
    no "who decided it" to report, just "it moved under you, try again"."""
    return jsonify({
        "message": "This record was changed by another request at the same moment. Please try again.",
        "retry": True,
    }), 409


def already_handled_response(record, table):
    """A clear, specific message instead of a generic error when a second
    approver acts on a record someone else already decided in the meantime
    (Part 8) — names who, and when, rather than just "already <status>"."""
    who = getattr(record, "approver_name_snapshot", None) or "someone else"
    decided_at = getattr(record, "decided_at", None)
    when = decided_at.strftime("%d %b %Y at %H:%M") if decided_at else None
    verb = "approved" if record.status in ("approved", "active", "closed") else record.status.replace("_", " ")
    message = f"This {table} was already {verb} by {who}" + (f" at {when}" if when else "") + "."
    return jsonify({
        "message": message,
        "already_handled": True,
        "status": record.status,
        "decided_by": who,
        "decided_at": decided_at.isoformat() if decided_at else None,
    }), 409


def decide_record(user, model, record_id, status, table):
    """Shared approve/reject flow for loans and penalties — the only two
    categories still under maker-checker (Part 1.1).

    Phase 2 item 4: the row is locked (SELECT ... FOR UPDATE) before the
    status is read, so a second concurrent approve/reject for the same
    record blocks until the first transaction commits, then re-reads the
    now-decided status and gets already_handled_response() instead of
    applying a second time.
    """
    record = model.query.filter_by(id=record_id).with_for_update().first()
    if record is None:
        return error("not found", 404)
    denial = approval_denial(user, record)
    if denial:
        return approval_denied_response(denial, record)
    if record.status not in PENDING_STATUSES:
        return already_handled_response(record, table)
    if status == "rejected":
        reason = (request.get_json(silent=True) or {}).get("rejection_reason")
        if not reason:
            return error("rejection_reason is required")
        record.rejection_reason = reason
    if status == "approved" and isinstance(record, Penalty) and record.loan.status != "active":
        return error("penalties can only be applied to an active loan", 409)
    try:
        # Phase 2 item 4: everything from here through commit() is inside
        # the guard — a lazy-loaded relationship access (record.loan below)
        # can trigger an autoflush that raises StaleDataError on its own,
        # before the explicit commit() is ever reached.
        record.status = status
        record.decided_at = datetime.utcnow()
        if hasattr(record, "approver_name_snapshot"):
            # Whoever just decided it, approve or reject — so a later stale
            # attempt can always be told who to blame/thank (Part 8).
            record.approver_name_snapshot = user.name
        if status == "approved":
            record.approved_by = user.id
            if isinstance(record, Loan):
                record.status = "active"
            if isinstance(record, Penalty):
                record.loan.outstanding_balance = money(record.loan.outstanding_balance + record.amount)
                resync_open_row_interest(record.loan)
        # No self-approved flag/badge of any kind under the tier model (Part 2) —
        # a department_manager+ approving their own record is recorded exactly
        # like any other approval.
        audit(user, status.upper(), table, record.id)
        db.session.commit()
    except StaleDataError:
        # Phase 2 item 4: lost the race (e.g. a concurrent penalty approval
        # already bumped the SAME loan's outstanding_balance). If this
        # exact record was also the one decided elsewhere, say so; otherwise
        # it's a plain "try again" — not a double-decision on this record.
        db.session.rollback()
        fresh = model.query.get(record_id)
        if fresh is not None and fresh.status not in PENDING_STATUSES:
            return already_handled_response(fresh, table)
        return retry_conflict_response()
    if status == "approved" and isinstance(record, Loan):
        deliver_loan_schedule(record)
    return jsonify({table.rstrip("s"): json_row(record)})


def deliver_loan_schedule(loan):
    """On approval, send the borrower their terms and full schedule (email, async).

    The PDF download and WhatsApp share are available from the loan's own page
    at any time; this is the automatic delivery that approval triggers.
    """
    borrower = loan.borrower
    if not borrower or not borrower.email:
        return
    reference = f"Loan #{loan.id}"
    send_email_async("loan_approved", borrower.email, {
        "borrower_name": borrower.name, "loan_reference": reference,
        "principal_amount": str(loan.principal_amount), "interest_rate": str(loan.interest_rate),
        "term_months": loan.term_months,
    })
    rows = [
        {
            "due_date": row.due_date.isoformat(),
            "principal_portion": str(row.principal_portion),
            "interest_portion": str(row.interest_portion),
            "payment_amount": str(row.expected_amount),
        }
        for row in sorted(loan.schedules, key=lambda row: row.due_date)
    ]
    send_email_async("loan_schedule", borrower.email, {
        "borrower_name": borrower.name, "loan_reference": reference, "schedule": rows,
    })


@operations_bp.post("/loans/<int:record_id>/approve")
@auth_required
def approve_loan(user, record_id): return decide_record(user, Loan, record_id, "approved", "loan")


@operations_bp.post("/loans/<int:record_id>/reject")
@auth_required
def reject_loan(user, record_id): return decide_record(user, Loan, record_id, "rejected", "loan")


@operations_bp.get("/loans/<int:loan_id>/schedule/export")
@auth_required
def export_loan_schedule(_user, loan_id):
    """Branded amortization schedule PDF — available in any loan status, draft onward."""
    loan = Loan.query.get_or_404(loan_id)
    return send_file(
        schedule_pdf(loan), as_attachment=True,
        download_name=f"loan-{loan.id}-schedule.pdf",
        mimetype="application/pdf",
    )


@operations_bp.post("/penalties/<int:record_id>/approve")
@auth_required
def approve_penalty(user, record_id): return decide_record(user, Penalty, record_id, "approved", "penalty")


@operations_bp.post("/penalties/<int:record_id>/reject")
@auth_required
def reject_penalty(user, record_id): return decide_record(user, Penalty, record_id, "rejected", "penalty")


@operations_bp.post("/penalties/<int:record_id>/reverse")
@permission_required("penalties:approve")
def reverse_penalty(user, record_id):
    """Phase 2 item 4: locked (SELECT ... FOR UPDATE) so two concurrent
    reversal attempts can't both pass the status check and both debit the
    loan's outstanding_balance."""
    penalty = Penalty.query.filter_by(id=record_id).with_for_update().first()
    if penalty is None:
        return error("not found", 404)
    if penalty.status != "approved":
        return error("only an approved penalty can be reversed", 400)
    if penalty.approved_by == user.id:
        return error("the original approver cannot reverse this penalty", 403)
    data = request.get_json(silent=True) or {}
    reason = data.get("reason")
    if not reason:
        return error("reason is required")
    try:
        # Phase 2 item 4: see decide_record()'s comment — penalty.loan below
        # is this request's first access of that relationship, and it can
        # autoflush-and-conflict before the explicit commit() below.
        penalty.status = "reversed"
        penalty.reversed_at = datetime.utcnow()
        penalty.reversed_by = user.id
        penalty.reversed_by_name_snapshot = user.name
        penalty.reversal_reason = reason
        penalty.loan.outstanding_balance = money(penalty.loan.outstanding_balance - penalty.amount)
        resync_open_row_interest(penalty.loan)
        audit(user, "REVERSE", "penalties", penalty.id, reason)
        db.session.commit()
    except StaleDataError:
        db.session.rollback()
        fresh = Penalty.query.get(record_id)
        if fresh is not None and fresh.status != "approved":
            return already_handled_response(fresh, "penalty")
        return retry_conflict_response()
    return jsonify({"penalty": json_row(penalty)})


# --------------------------------------------------------------------- assets

@operations_bp.get("/asset-types")
@auth_required
def list_asset_types(_user):
    return jsonify({"asset_types": [json_row(row) for row in AssetType.query.filter_by(is_active=True).order_by(AssetType.name).all()]})


@operations_bp.post("/asset-types")
@role_required("ceo", "head_manager")
def create_asset_type(user):
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return error("name is required")
    asset_type = AssetType(name=name, is_active=True)
    db.session.add(asset_type)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("an asset type with this name already exists", 409)
    audit(user, "CREATE", "asset_types", asset_type.id)
    return jsonify({"asset_type": json_row(asset_type)}), 201


@operations_bp.get("/assets")
@auth_required
def list_assets(_user):
    rows = []
    for asset in Asset.query.filter_by(is_active=True).all():
        item = json_row(asset)
        item["asset_type_name"] = asset.asset_type.name if asset.asset_type else asset.type
        rows.append(item)
    return jsonify({"assets": rows})


@operations_bp.post("/assets")
@permission_required("assets:manage")
def create_asset(user):
    data = request.get_json(silent=True) or {}
    try:
        asset_type = AssetType.query.get(data["asset_type_id"]) if data.get("asset_type_id") else None
        asset = Asset(
            name=data["name"], type=(asset_type.name if asset_type else data.get("type", "Other")),
            asset_type_id=asset_type.id if asset_type else None,
            value=parse_money(data.get("value"), "value"),
            date_acquired=parse_date(data["date_acquired"], "date_acquired"), notes=data.get("notes"), is_active=True,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return error(str(exc))
    db.session.add(asset)
    audit(user, "CREATE", "assets", None)
    db.session.commit()
    return jsonify({"asset": json_row(asset)}), 201


@operations_bp.put("/assets/<int:asset_id>")
@permission_required("assets:manage")
def update_asset(user, asset_id):
    asset = Asset.query.get_or_404(asset_id)
    data = request.get_json(silent=True) or {}
    try:
        if "asset_type_id" in data:
            asset_type = AssetType.query.get(data["asset_type_id"]) if data["asset_type_id"] else None
            asset.asset_type_id = asset_type.id if asset_type else None
            if asset_type:
                asset.type = asset_type.name
        for field in ("name", "notes"):
            if field in data:
                setattr(asset, field, data[field])
        if "value" in data: asset.value = parse_money(data["value"], "value")
        if "date_acquired" in data: asset.date_acquired = parse_date(data["date_acquired"], "date_acquired")
    except (TypeError, ValueError) as exc:
        return error(str(exc))
    db.session.commit()
    return jsonify({"asset": json_row(asset)})


@operations_bp.delete("/assets/<int:asset_id>")
@permission_required("assets:manage")
def delete_asset(user, asset_id):
    asset = Asset.query.get_or_404(asset_id)
    asset.is_active = False
    audit(user, "ARCHIVE", "assets", asset.id)
    db.session.commit()
    return jsonify({"message": "asset archived"})


# -------------------------------------------------------------------- capital

def _sum(query_scalar):
    return Decimal(str(query_scalar or 0))


def capital_breakdown():
    """Every component of cash on hand, computed live (never cached) — the
    'how this is calculated' panel shows exactly this (Part 4.4)."""
    from sqlalchemy import func

    opening_row = CapitalEntry.query.filter_by(entry_type="opening").order_by(CapitalEntry.created_at.desc()).first()
    opening = opening_row.new_value if opening_row else Decimal("0")
    injections = _sum(db.session.query(func.coalesce(func.sum(CapitalEntry.amount), 0)).filter_by(entry_type="injection").scalar())
    withdrawals = _sum(db.session.query(func.coalesce(func.sum(CapitalEntry.amount), 0)).filter_by(entry_type="withdrawal").scalar())
    repayments_received = _sum(db.session.query(func.coalesce(func.sum(Repayment.amount_paid), 0)).scalar())
    principal_disbursed = _sum(
        db.session.query(func.coalesce(func.sum(Loan.principal_amount), 0))
        .filter(Loan.status.in_(["active", "closed"])).scalar()
    )
    expenses_total = _sum(db.session.query(func.coalesce(func.sum(Expense.amount), 0)).scalar())
    from models import PayrollBatch
    payroll_paid = sum(
        (Decimal(str(line.net_pay)) for batch in PayrollBatch.query.filter_by(status="paid").all() for line in batch.lines),
        Decimal("0"),
    )
    cash_on_hand = money(opening + injections - withdrawals + repayments_received - principal_disbursed - expenses_total - payroll_paid)
    loans_outstanding = _sum(
        db.session.query(func.coalesce(func.sum(Loan.outstanding_balance), 0)).filter(Loan.status == "active").scalar()
    )
    assets_value = _sum(db.session.query(func.coalesce(func.sum(Asset.value), 0)).filter_by(is_active=True).scalar())
    total_worth = money(cash_on_hand + loans_outstanding + assets_value)
    return {
        # PART 14: the exact Decimal, not yet rounded through a serialized
        # float - capital_projection() starts from this instead of round-
        # tripping cash_on_hand through float(); popped before jsonify.
        "_cash_on_hand_decimal": cash_on_hand,
        "opening_capital": float(opening),
        "injections": float(injections),
        "withdrawals": float(withdrawals),
        "repayments_received": float(repayments_received),
        "loan_principal_disbursed": float(principal_disbursed),
        "recorded_expenses": float(expenses_total),
        "finalized_payroll": float(payroll_paid),
        "cash_on_hand": float(cash_on_hand),
        # Two distinct, clearly separate figures (Part 5) — never conflated:
        # the live sum of what borrowers still owe on ACTIVE loans (the
        # figure used everywhere else, e.g. the reducing-balance math), vs.
        # the lifetime sum of principal ever disbursed, active or closed,
        # which is never itself used in the reducing-balance calculations.
        "outstanding_balance": float(loans_outstanding),
        "total_disbursed": float(principal_disbursed),
        "assets_value": float(assets_value),
        "total_worth": float(total_worth),
        "has_opening_entry": opening_row is not None,
    }


@operations_bp.get("/capital/summary")
@permission_required("capital:view")
def capital_summary(_user):
    breakdown = capital_breakdown()
    breakdown.pop("_cash_on_hand_decimal", None)
    return jsonify(breakdown)


@operations_bp.get("/capital/projection")
@permission_required("capital:view")
def capital_projection(_user):
    """Next 6 months of scheduled collections from active loans, minus the
    latest payroll total and the 3-month average of expenses (Part 4.5)."""
    from sqlalchemy import func

    from models import PayrollBatch

    today = local_today()
    months = []
    cursor = date(today.year, today.month, 1)
    for _ in range(6):
        year, month = cursor.year, (cursor.month % 12) + 1
        year = year + 1 if cursor.month == 12 else year
        next_cursor = date(year, month, 1)
        months.append((cursor, next_cursor))
        cursor = next_cursor

    expected_by_month = {}
    for start, end in months:
        total = db.session.query(func.coalesce(func.sum(PaymentSchedule.expected_amount), 0)).join(Loan).filter(
            Loan.status == "active", PaymentSchedule.due_date >= start, PaymentSchedule.due_date < end,
        ).scalar()
        expected_by_month[start] = _sum(total)

    latest_batch = PayrollBatch.query.filter_by(status="paid").order_by(PayrollBatch.finalized_at.desc()).first()
    latest_payroll = sum((Decimal(str(line.net_pay)) for line in latest_batch.lines), Decimal("0")) if latest_batch else Decimal("0")

    three_months_ago = today.replace(day=1) - timedelta(days=90)
    recent_expenses = Expense.query.filter(Expense.date >= three_months_ago).all()
    span_months = max(1, len({(e.date.year, e.date.month) for e in recent_expenses}) or 1)
    avg_expenses = money(sum((Decimal(str(e.amount)) for e in recent_expenses), Decimal("0")) / span_months) if recent_expenses else Decimal("0")

    running = capital_breakdown()["_cash_on_hand_decimal"]
    rows = []
    for start, _end in months:
        expected = expected_by_month[start]
        running = money(running + expected - latest_payroll - avg_expenses)
        rows.append({
            "month": start.strftime("%Y-%m"),
            "expected_collections": float(expected),
            "estimated_payroll": float(latest_payroll),
            "average_expenses": float(avg_expenses),
            "projected_cash_end_of_month": float(running),
        })
    return jsonify({"projection": rows, "note": "Estimate only — based on scheduled collections, the latest finalized payroll, and the 3-month average of recorded expenses."})


@operations_bp.get("/capital/entries")
@permission_required("capital:view")
def list_capital_entries(_user):
    entry_type = request.args.get("type")
    query = CapitalEntry.query
    if entry_type:
        query = query.filter_by(entry_type=entry_type)
    rows = query.order_by(CapitalEntry.created_at.desc()).all()
    return jsonify({"capital_entries": [json_row(row) for row in rows]})


@operations_bp.get("/capital/opening")
@permission_required("capital:view")
def list_capital_opening(_user):
    rows = CapitalEntry.query.filter_by(entry_type="opening").order_by(CapitalEntry.created_at.desc()).all()
    return jsonify({"capital_entries": [json_row(row) for row in rows]})


@operations_bp.post("/capital/opening")
@permission_required("capital:manage")
def set_opening_capital(user):
    """One-time setup: no reason needed. Any later correction requires CEO and
    a reason, and the previous value is kept in history (Part 4.2)."""
    data = request.get_json(silent=True) or {}
    try:
        new_value = parse_money(data.get("new_value"), "new_value")
    except ValueError as exc:
        return error(str(exc))
    latest = CapitalEntry.query.filter_by(entry_type="opening").order_by(CapitalEntry.created_at.desc()).first()
    reason = data.get("reason")
    if latest is not None:
        if user.role != "ceo":
            return error("only ceo can correct the opening capital figure", 403)
        if not reason:
            return error("reason is required to correct the opening capital figure")
    previous_value = latest.new_value if latest else Decimal("0")
    entry = CapitalEntry(
        entry_type="opening", previous_value=previous_value, new_value=new_value,
        reason=reason, date=data.get("date") and parse_date(data["date"], "date"),
        changed_by=user.id, changed_by_name_snapshot=user.name,
    )
    db.session.add(entry)
    db.session.flush()
    audit(user, "SET_OPENING_CAPITAL", "capital_entries", entry.id, reason)
    db.session.commit()
    return jsonify({"capital_entry": json_row(entry)}), 201


@operations_bp.post("/capital/injections")
@permission_required("capital:manage")
def create_injection(user):
    data = request.get_json(silent=True) or {}
    try:
        amount = parse_money(data.get("amount"), "amount", min_value=Decimal("0.01"))
        entry_date = parse_date(data["date"], "date")
    except (KeyError, ValueError) as exc:
        return error(str(exc))
    entry = CapitalEntry(entry_type="injection", amount=amount, date=entry_date, note=data.get("note"), changed_by=user.id, changed_by_name_snapshot=user.name)
    db.session.add(entry)
    db.session.flush()
    audit(user, "CAPITAL_INJECTION", "capital_entries", entry.id, str(amount))
    db.session.commit()
    return jsonify({"capital_entry": json_row(entry)}), 201


@operations_bp.post("/capital/withdrawals")
@permission_required("capital:manage")
def create_withdrawal(user):
    data = request.get_json(silent=True) or {}
    try:
        amount = parse_money(data.get("amount"), "amount", min_value=Decimal("0.01"))
        entry_date = parse_date(data["date"], "date")
    except (KeyError, ValueError) as exc:
        return error(str(exc))
    entry = CapitalEntry(entry_type="withdrawal", amount=amount, date=entry_date, note=data.get("note"), changed_by=user.id, changed_by_name_snapshot=user.name)
    db.session.add(entry)
    db.session.flush()
    audit(user, "CAPITAL_WITHDRAWAL", "capital_entries", entry.id, str(amount))
    db.session.commit()
    return jsonify({"capital_entry": json_row(entry)}), 201


# ---------------------------------------------------------------------- leave

@operations_bp.get("/leave-requests")
@auth_required
def list_leave_requests(user):
    query = LeaveRequest.query
    if request.args.get("employee_id"): query = query.filter_by(employee_id=request.args["employee_id"])
    if request.args.get("status"): query = query.filter_by(status=request.args["status"])
    rows = [
        json_row(row, {
            "employee_name": row.employee.name if row.employee else None,
            "can_decide": can_decide(user, row),
        })
        for row in query.order_by(LeaveRequest.id.desc()).all()
    ]
    return jsonify({"leave_requests": rows})


@operations_bp.post("/leave-requests")
@auth_required
def create_leave(user):
    data = request.get_json(silent=True) or {}
    try:
        employee_id = int(data["employee_id"])
        own_employee = Employee.query.filter_by(user_id=user.id).first()
        acting_for_self = own_employee is not None and own_employee.id == employee_id
        if not acting_for_self and not has_permission(user, "leave:manage"):
            return error("you can only request leave for yourself", 403)
        leave = LeaveRequest(
            employee_id=employee_id, created_by=user.id, creator_name_snapshot=user.name,
            leave_type=data["leave_type"], start_date=parse_date(data["start_date"], "start_date"),
            end_date=parse_date(data["end_date"], "end_date"), reason=data.get("reason"), status="pending",
        )
    except (KeyError, TypeError, ValueError) as exc:
        return error(str(exc))
    db.session.add(leave)
    db.session.flush()
    audit(user, "CREATE", "leave_requests", leave.id)
    db.session.commit()
    return jsonify({"leave_request": json_row(leave)}), 201


def decide_leave(user, leave_id, status):
    """Simple request -> decide: leave:manage is enough, no creator-must-differ
    check (Part 1.1 — leave is explicitly not maker-checker).

    Phase 2 item 4: locked (SELECT ... FOR UPDATE) for the same reason as
    decide_record() above.
    """
    leave = LeaveRequest.query.filter_by(id=leave_id).with_for_update().first()
    if leave is None:
        return error("not found", 404)
    if not has_permission(user, "leave:manage"):
        return error("You don't have permission to do this.", 403)
    if leave.status != "pending":
        return already_handled_response(leave, "leave request")
    data = request.get_json(silent=True) or {}
    if status == "rejected":
        reason = data.get("rejection_reason")
        if not reason: return error("rejection_reason is required")
        leave.rejection_reason = reason
    if status == "approved" and ("start_date" in data or "end_date" in data):
        # The approver may adjust the requested range before approving
        # (Part 9.2 — e.g. for a calendar/staffing conflict) — the ORIGINAL
        # ask is preserved the first time this happens, never overwritten.
        try:
            new_start = parse_date(data["start_date"], "start_date") if "start_date" in data else leave.start_date
            new_end = parse_date(data["end_date"], "end_date") if "end_date" in data else leave.end_date
        except (KeyError, TypeError, ValueError) as exc:
            return error(str(exc))
        if new_end < new_start:
            return error("end_date cannot be before start_date")
        if (new_start, new_end) != (leave.start_date, leave.end_date):
            if leave.original_start_date is None:
                leave.original_start_date = leave.start_date
                leave.original_end_date = leave.end_date
            leave.start_date, leave.end_date = new_start, new_end
    leave.status = status
    leave.decided_at = datetime.utcnow()
    leave.approver_name_snapshot = user.name
    if status == "approved":
        leave.approved_by = user.id
    audit(user, status.upper(), "leave_requests", leave.id)
    try:
        db.session.commit()
    except StaleDataError:
        db.session.rollback()
        fresh = LeaveRequest.query.get(leave_id)
        if fresh is not None and fresh.status != "pending":
            return already_handled_response(fresh, "leave request")
        return retry_conflict_response()
    return jsonify({"leave_request": json_row(leave)})


@operations_bp.post("/leave-requests/<int:leave_id>/approve")
@auth_required
def approve_leave(user, leave_id): return decide_leave(user, leave_id, "approved")


@operations_bp.post("/leave-requests/<int:leave_id>/reject")
@auth_required
def reject_leave(user, leave_id): return decide_leave(user, leave_id, "rejected")
