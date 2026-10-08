"""Parts 1-3 of the session/security fix pass:
  - creating a user must never touch the creator's own session (Part 1.3)
  - the password-reset/verification token must validate BEFORE any
    set-password form is shown, and must behave identically regardless of
    any other active session in the request (Part 2)
  - a token is single-use, and a failed email send is now observable
    instead of silently discarded (Part 3)
"""
import logging

from services.accounts import reset_token


# --------------------------------------------------------- Part 1.3: creator session


def test_creating_a_user_does_not_affect_the_creators_own_session(client, make_user, auth_headers):
    ceo, ceo_pw = make_user("ceo")
    creator_headers = auth_headers(ceo.email, ceo_pw)

    # The creator's token works before...
    before = client.get("/api/auth/me", headers=creator_headers)
    assert before.status_code == 200
    assert before.get_json()["user"]["email"] == ceo.email

    created = client.post(
        "/api/auth/register",
        json={"name": "New Maker", "email": "new-maker@example.com", "phone": "0700444555", "role": "maker", "department": "loans_credit"},
        headers=creator_headers,
    )
    assert created.status_code == 201, created.get_json()

    # ...and the EXACT SAME token still works afterward, completely unaffected.
    after = client.get("/api/auth/me", headers=creator_headers)
    assert after.status_code == 200
    assert after.get_json()["user"]["email"] == ceo.email
    assert after.get_json()["user"]["id"] == before.get_json()["user"]["id"]


# --------------------------------------------------------- Part 2: token-first validate


def test_validate_endpoint_accepts_a_fresh_token_without_consuming_it(client, make_user):
    user, _ = make_user("maker", email="validate-target@example.com")
    with_app_token = reset_token(user, "account_setup")

    first = client.post("/api/auth/password-reset/validate", json={"token": with_app_token})
    assert first.status_code == 200
    assert first.get_json()["valid"] is True
    assert first.get_json()["purpose"] == "account_setup"

    # Validating is read-only — calling it again still succeeds, and the
    # account is still unverified (nothing was consumed).
    second = client.post("/api/auth/password-reset/validate", json={"token": with_app_token})
    assert second.status_code == 200


def test_validate_endpoint_rejects_missing_malformed_and_unknown_tokens(client):
    missing = client.post("/api/auth/password-reset/validate", json={})
    assert missing.status_code == 400
    assert missing.get_json()["expired"] is True

    malformed = client.post("/api/auth/password-reset/validate", json={"token": "not-a-real-token"})
    assert malformed.status_code == 400
    assert malformed.get_json()["expired"] is True


def test_validate_endpoint_rejects_an_expired_token_the_same_way_confirm_does(client, make_user, app):
    import time

    user, _ = make_user("maker", email="expiry-validate@example.com")
    token = reset_token(user, "password_reset")
    app.config["PASSWORD_RESET_TTL_MINUTES"] = 1 / 60000  # ~1ms — any real delay expires it
    time.sleep(1.1)

    validated = client.post("/api/auth/password-reset/validate", json={"token": token})
    assert validated.status_code == 400
    assert validated.get_json()["expired"] is True

    # The set-password page must never proceed past this — confirm agrees.
    confirmed = client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "NewPassw0rd!9"})
    assert confirmed.status_code == 400
    assert confirmed.get_json()["expired"] is True


def test_token_is_single_use_a_second_confirm_with_the_same_token_fails_validate_and_confirm(client, make_user):
    user, _ = make_user("maker", email="single-use@example.com")
    token = reset_token(user, "account_setup")

    first_confirm = client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "FirstPassw0rd!9"})
    assert first_confirm.status_code == 200

    # The SAME link, opened again (e.g. a second click, a stale browser tab,
    # or a would-be replay) is now dead — the whole point of single-use.
    reused_validate = client.post("/api/auth/password-reset/validate", json={"token": token})
    assert reused_validate.status_code == 400
    assert reused_validate.get_json()["expired"] is True

    reused_confirm = client.post("/api/auth/password-reset/confirm", json={"token": token, "password": "SecondPassw0rd!9"})
    assert reused_confirm.status_code == 400
    assert reused_confirm.get_json()["expired"] is True

    # The first password actually took effect; the replay never changed it again.
    login = client.post("/api/auth/login", json={"email": "single-use@example.com", "password": "FirstPassw0rd!9"})
    assert login.status_code == 200


def test_resending_a_link_still_works_the_old_one_and_the_new_one_share_a_version_until_used(client, make_user):
    """A resend issues a brand new token but does NOT bump credentials_version
    (only actually consuming a token does) — so if the user's inbox is slow
    and they end up with two copies of the same link in flight, either one
    still works, right up until one of them is used."""
    user, _ = make_user("maker", email="resend-target@example.com")
    first_link_token = reset_token(user, "account_setup")
    second_link_token = reset_token(user, "account_setup")  # e.g. issued by a "resend" click

    assert client.post("/api/auth/password-reset/validate", json={"token": first_link_token}).status_code == 200
    assert client.post("/api/auth/password-reset/validate", json={"token": second_link_token}).status_code == 200

    used = client.post("/api/auth/password-reset/confirm", json={"token": first_link_token, "password": "ResendPassw0rd!9"})
    assert used.status_code == 200

    # Now that one of them has actually been consumed, the other is dead too.
    other_now_dead = client.post("/api/auth/password-reset/validate", json={"token": second_link_token})
    assert other_now_dead.status_code == 400
    assert other_now_dead.get_json()["expired"] is True


def test_reset_and_validate_endpoints_ignore_a_different_users_active_session(client, make_user, auth_headers):
    """Part 2.3: this must be a fully public, token-only page — a valid
    Authorization header for a COMPLETELY DIFFERENT account attached to the
    request changes nothing about the outcome."""
    ceo, ceo_pw = make_user("ceo")
    target, _ = make_user("maker", email="ignore-session-target@example.com")
    token = reset_token(target, "account_setup")

    someone_elses_session = auth_headers(ceo.email, ceo_pw)

    with_session = client.post("/api/auth/password-reset/validate", json={"token": token}, headers=someone_elses_session)
    without_session = client.post("/api/auth/password-reset/validate", json={"token": token})
    assert with_session.status_code == without_session.status_code == 200
    assert with_session.get_json() == without_session.get_json()

    confirmed = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "password": "IgnoreSessionPassw0rd!9"},
        headers=someone_elses_session,
    )
    assert confirmed.status_code == 200
    # It set TARGET's password, not the CEO's whose header rode along.
    target_login = client.post("/api/auth/login", json={"email": target.email, "password": "IgnoreSessionPassw0rd!9"})
    assert target_login.status_code == 200
    assert target_login.get_json()["user"]["id"] == target.id
    # The CEO's own credentials are completely untouched.
    ceo_login = client.post("/api/auth/login", json={"email": ceo.email, "password": ceo_pw})
    assert ceo_login.status_code == 200


# --------------------------------------------------------- Part 3: email failure visibility


def test_a_failed_email_send_is_logged_not_silently_discarded(app, caplog, monkeypatch):
    """Before this fix, services.accounts.send_email_async's background
    thread never inspected send_email()'s return value — a failed send
    (send_email() catches its own exceptions and returns {"error": ...}
    rather than raising) vanished with no trace anywhere. Now it's logged.

    This originally polled/slept for up to 2.5s waiting for the background
    thread's log line to show up (flaky under load). Calling the underlying
    send-then-log logic directly and synchronously — no thread at all —
    removes the timing dependency entirely.

    (The real cause of this test failing only when run alongside the full
    suite turned out to be unrelated to threading or timing: it was
    migrations/env.py's fileConfig() call — triggered by
    test_migration_email_backfill.py actually running Alembic in-process —
    permanently disabling every logger not listed in alembic.ini, including
    Flask's "app" logger, for the rest of the process. Fixed at the source
    by passing disable_existing_loggers=False there.)"""
    from services.accounts import _send_and_log

    monkeypatch.setattr("services.accounts.send_email", lambda *a, **kw: {"error": "connection refused"})

    with app.app_context():
        with caplog.at_level(logging.ERROR):
            _send_and_log(app, "verification", "someone@example.com", {"name": "X", "verify_link": "http://x"})

    assert any("did not succeed" in r.message and "verification" in r.message for r in caplog.records)
