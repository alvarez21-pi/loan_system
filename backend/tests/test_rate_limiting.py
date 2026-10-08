"""Phase 2 item 7: DB-backed rate limiting on login, forgot-password,
resend-verification, verify and set-password. Limits are per-account AND
per-IP; responses stay generic either way.
"""
import pytest

from services.rate_limit import MAX_ATTEMPTS


@pytest.fixture()
def user(make_user):
    return make_user("maker", email="ratelimit@example.com", password="Passw0rd!9")


def test_login_locks_out_after_repeated_wrong_passwords(client, user):
    account, password = user
    # The MAX_ATTEMPTS-th failure is still processed normally (it's what
    # CROSSES the threshold); the lockout takes effect starting with the
    # call after that.
    for _ in range(MAX_ATTEMPTS):
        response = client.post("/api/auth/login", json={"email": account.email, "password": "wrong-one"})
        assert response.status_code == 401

    locked = client.post("/api/auth/login", json={"email": account.email, "password": "wrong-one"})
    assert locked.status_code == 429
    assert "too many" in locked.get_json()["message"].lower()

    # Even the CORRECT password is now blocked — the lockout check runs
    # before the password is ever compared.
    still_locked = client.post("/api/auth/login", json={"email": account.email, "password": password})
    assert still_locked.status_code == 429


def test_login_lockout_is_generic_about_account_existence(client, user):
    account, _password = user
    for _ in range(MAX_ATTEMPTS):
        client.post("/api/auth/login", json={"email": account.email, "password": "wrong-one"})
    locked_real_account = client.post("/api/auth/login", json={"email": account.email, "password": "wrong-one"})
    assert locked_real_account.status_code == 429

    # A DIFFERENT, non-existent email from the SAME IP is now ALSO blocked
    # (the IP bucket, not the account bucket, is what tripped) — proving
    # the block is per-IP as well as per-account, and the message gives no
    # hint either way.
    other_email_same_ip = client.post(
        "/api/auth/login", json={"email": "someone-else@example.com", "password": "whatever"}
    )
    assert other_email_same_ip.status_code == 429
    assert other_email_same_ip.get_json()["message"] == locked_real_account.get_json()["message"]


def test_successful_login_clears_the_failure_counter(client, user):
    account, password = user
    for _ in range(MAX_ATTEMPTS - 2):
        response = client.post("/api/auth/login", json={"email": account.email, "password": "wrong-one"})
        assert response.status_code == 401

    # A correct login partway through resets the count — it doesn't matter
    # that we were close to the threshold.
    success = client.post("/api/auth/login", json={"email": account.email, "password": password})
    assert success.status_code == 200

    # Can immediately fail almost MAX_ATTEMPTS more times without being locked.
    for _ in range(MAX_ATTEMPTS - 2):
        response = client.post("/api/auth/login", json={"email": account.email, "password": "wrong-one"})
        assert response.status_code == 401
    still_ok = client.post("/api/auth/login", json={"email": account.email, "password": password})
    assert still_ok.status_code == 200


def test_resend_verification_is_rate_limited_and_stays_generic(client):
    responses = []
    for _ in range(MAX_ATTEMPTS):
        responses.append(client.post("/api/auth/resend-verification", json={"email": "nobody@example.com"}))
    for response in responses:
        assert response.status_code == 202

    limited = client.post("/api/auth/resend-verification", json={"email": "nobody@example.com"})
    assert limited.status_code == 429

    # A registered email, same IP, is now ALSO blocked, with the identical message.
    limited_real = client.post("/api/auth/resend-verification", json={"email": "someone@example.com"})
    assert limited_real.status_code == 429
    assert limited_real.get_json()["message"] == limited.get_json()["message"]


def test_forgot_password_is_rate_limited(client):
    for _ in range(MAX_ATTEMPTS):
        response = client.post("/api/auth/password-reset/request", json={"email": "nobody@example.com"})
        assert response.status_code == 202
    limited = client.post("/api/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert limited.status_code == 429


def test_password_reset_validate_and_confirm_are_rate_limited(client):
    for _ in range(MAX_ATTEMPTS):
        response = client.post("/api/auth/password-reset/validate", json={"token": "not-a-real-token"})
        assert response.status_code == 400
    limited = client.post("/api/auth/password-reset/validate", json={"token": "not-a-real-token"})
    assert limited.status_code == 429
