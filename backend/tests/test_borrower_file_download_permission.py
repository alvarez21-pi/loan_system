"""Phase 2 item 9 / F-31: GET /api/borrowers/<id>/<kind> (photo, id-document)
used to be @auth_required only — any logged-in account could download a
borrower's photo or ID document, including an HR/Finance department_manager
with no business reason to. Now gated behind borrowers:view/borrowers:manage
(the same permission the rest of the borrowers module uses), and every
download is audited.
"""
import io

import pytest
from PIL import Image


def make_png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), color="red").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


@pytest.fixture()
def borrower_with_photo(client, make_user, auth_headers):
    maker, maker_pw = make_user("maker", department="loans_credit")
    headers = auth_headers(maker.email, maker_pw)
    created = client.post("/api/borrowers", json={
        "name": "Photo Borrower", "phone": "0711222333", "id_number": "DL-1",
    }, headers=headers)
    assert created.status_code == 201, created.get_json()
    borrower_id = created.get_json()["borrower"]["id"]
    uploaded = client.post(
        f"/api/borrowers/{borrower_id}/photo",
        data={"file": (make_png_bytes(), "photo.png")},
        content_type="multipart/form-data",
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.get_json()
    return borrower_id


ALLOWED_ROLES = [
    ("ceo", None),
    ("head_manager", None),
    ("department_manager", "loans_credit"),
    ("checker", None),
    ("maker", None),
]
DENIED_ROLES = [
    ("department_manager", "hr"),
    ("department_manager", "finance"),
]


@pytest.mark.parametrize("role,department", ALLOWED_ROLES)
def test_roles_with_borrower_access_can_download_the_photo(
    client, borrower_with_photo, make_user, auth_headers, role, department
):
    # Login normalizes/lowercases the submitted email before querying, so
    # the email built here must already be all-lowercase (the literal
    # "None" from an unset department would otherwise never match).
    user, pw = make_user(role, department=department, email=f"{role}-{department or 'none'}-allowed@example.com".lower())
    headers = auth_headers(user.email, pw)
    response = client.get(f"/api/borrowers/{borrower_with_photo}/photo", headers=headers)
    assert response.status_code == 200, response.get_json() if response.is_json else response.status_code


@pytest.mark.parametrize("role,department", DENIED_ROLES)
def test_hr_and_finance_managers_cannot_download_a_loan_borrowers_photo(
    client, borrower_with_photo, make_user, auth_headers, role, department
):
    user, pw = make_user(role, department=department, email=f"{role}-{department or 'none'}-denied@example.com".lower())
    headers = auth_headers(user.email, pw)
    response = client.get(f"/api/borrowers/{borrower_with_photo}/photo", headers=headers)
    assert response.status_code == 403, response.get_json()


def test_download_is_written_to_the_audit_trail(client, borrower_with_photo, make_user, auth_headers, app):
    from models import AuditLog

    ceo, ceo_pw = make_user("ceo")
    headers = auth_headers(ceo.email, ceo_pw)
    response = client.get(f"/api/borrowers/{borrower_with_photo}/photo", headers=headers)
    assert response.status_code == 200

    with app.app_context():
        entry = AuditLog.query.filter_by(table_name="borrowers", record_id=borrower_with_photo, action="DOWNLOAD_PHOTO").first()
        assert entry is not None
        assert entry.actor_email_snapshot == ceo.email
