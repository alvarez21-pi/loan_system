"""Phase 2 item 3: CEO_EMAIL/CEO_PASSWORD have no fallback, weak passwords
are refused, and the seeded CEO must change their password on first login.
"""
import importlib
import os

import pytest


@pytest.fixture()
def seed_env(monkeypatch, app):
    """seed_ceo.main() reads os.environ directly and uses create_app()
    itself — run it against the SAME temp sqlite db the `app` fixture
    already set up (DATABASE_URL/UPLOAD_DIR), inside that app's context."""
    for key in ("CEO_NAME", "CEO_EMAIL", "CEO_PASSWORD", "CEO_PHONE", "CEO_RESET_PASSWORD"):
        monkeypatch.delenv(key, raising=False)

    def _run():
        import seed_ceo
        importlib.reload(seed_ceo)
        seed_ceo.main()

    return _run


def test_seed_refuses_without_ceo_email(seed_env, monkeypatch):
    monkeypatch.setenv("CEO_NAME", "Test CEO")
    monkeypatch.setenv("CEO_PASSWORD", "aStrongPassw0rd!")
    with pytest.raises(SystemExit, match="(?i)ceo_email"):
        seed_env()


def test_seed_refuses_without_ceo_password(seed_env, monkeypatch):
    monkeypatch.setenv("CEO_NAME", "Test CEO")
    monkeypatch.setenv("CEO_EMAIL", "ceo@test.invalid")
    with pytest.raises(SystemExit, match="(?i)ceo_password"):
        seed_env()


def test_seed_refuses_a_short_password(seed_env, monkeypatch):
    monkeypatch.setenv("CEO_NAME", "Test CEO")
    monkeypatch.setenv("CEO_EMAIL", "ceo@test.invalid")
    monkeypatch.setenv("CEO_PASSWORD", "short12345")  # 10 chars, under the 12-char minimum
    with pytest.raises(SystemExit, match="(?i)12 characters"):
        seed_env()


def test_seed_refuses_an_obvious_password(seed_env, monkeypatch):
    monkeypatch.setenv("CEO_NAME", "Test CEO")
    monkeypatch.setenv("CEO_EMAIL", "ceo@test.invalid")
    # 12 characters (clears the length check) but on the obvious-passwords list.
    monkeypatch.setenv("CEO_PASSWORD", "password1234")
    with pytest.raises(SystemExit, match="(?i)common"):
        seed_env()


def test_seed_succeeds_with_a_strong_password_and_forces_change(seed_env, monkeypatch, app):
    from models import User

    monkeypatch.setenv("CEO_NAME", "Test CEO")
    monkeypatch.setenv("CEO_EMAIL", "ceo@test.invalid")
    monkeypatch.setenv("CEO_PASSWORD", "aStrongCeoPassw0rd!")
    seed_env()

    user = User.query.filter_by(role="ceo").first()
    assert user is not None
    assert user.email == "ceo@test.invalid"
    assert user.must_change_password is True


def test_login_with_must_change_password_still_returns_a_token_but_flags_it(client, seed_env, monkeypatch):
    monkeypatch.setenv("CEO_NAME", "Test CEO")
    monkeypatch.setenv("CEO_EMAIL", "ceo@test.invalid")
    monkeypatch.setenv("CEO_PASSWORD", "aStrongCeoPassw0rd!")
    seed_env()

    response = client.post("/api/auth/login", json={"email": "ceo@test.invalid", "password": "aStrongCeoPassw0rd!"})
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["user"]["must_change_password"] is True
    assert body["access_token"]


def test_must_change_password_blocks_other_endpoints_but_not_me_or_change_password(client, seed_env, monkeypatch):
    monkeypatch.setenv("CEO_NAME", "Test CEO")
    monkeypatch.setenv("CEO_EMAIL", "ceo@test.invalid")
    monkeypatch.setenv("CEO_PASSWORD", "aStrongCeoPassw0rd!")
    seed_env()
    token = client.post(
        "/api/auth/login", json={"email": "ceo@test.invalid", "password": "aStrongCeoPassw0rd!"}
    ).get_json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    blocked = client.get("/api/borrowers", headers=headers)
    assert blocked.status_code == 403
    assert blocked.get_json()["must_change_password"] is True

    allowed = client.get("/api/auth/me", headers=headers)
    assert allowed.status_code == 200


def test_change_password_wrong_current_password_rejected(client, seed_env, monkeypatch):
    monkeypatch.setenv("CEO_NAME", "Test CEO")
    monkeypatch.setenv("CEO_EMAIL", "ceo@test.invalid")
    monkeypatch.setenv("CEO_PASSWORD", "aStrongCeoPassw0rd!")
    seed_env()
    token = client.post(
        "/api/auth/login", json={"email": "ceo@test.invalid", "password": "aStrongCeoPassw0rd!"}
    ).get_json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    rejected = client.post(
        "/api/auth/change-password",
        json={"current_password": "wrong-password", "new_password": "aBrandNewPassw0rd!"},
        headers=headers,
    )
    assert rejected.status_code == 401


def test_change_password_weak_new_password_rejected(client, seed_env, monkeypatch):
    monkeypatch.setenv("CEO_NAME", "Test CEO")
    monkeypatch.setenv("CEO_EMAIL", "ceo@test.invalid")
    monkeypatch.setenv("CEO_PASSWORD", "aStrongCeoPassw0rd!")
    seed_env()
    token = client.post(
        "/api/auth/login", json={"email": "ceo@test.invalid", "password": "aStrongCeoPassw0rd!"}
    ).get_json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    rejected = client.post(
        "/api/auth/change-password",
        json={"current_password": "aStrongCeoPassw0rd!", "new_password": "short"},
        headers=headers,
    )
    assert rejected.status_code == 400


def test_change_password_success_clears_the_flag_and_unblocks_other_endpoints(client, seed_env, monkeypatch):
    monkeypatch.setenv("CEO_NAME", "Test CEO")
    monkeypatch.setenv("CEO_EMAIL", "ceo@test.invalid")
    monkeypatch.setenv("CEO_PASSWORD", "aStrongCeoPassw0rd!")
    seed_env()
    token = client.post(
        "/api/auth/login", json={"email": "ceo@test.invalid", "password": "aStrongCeoPassw0rd!"}
    ).get_json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    changed = client.post(
        "/api/auth/change-password",
        json={"current_password": "aStrongCeoPassw0rd!", "new_password": "aBrandNewCeoPassw0rd!"},
        headers=headers,
    )
    assert changed.status_code == 200, changed.get_json()
    assert changed.get_json()["user"]["must_change_password"] is False

    now_allowed = client.get("/api/borrowers", headers=headers)
    assert now_allowed.status_code == 200

    # The old password no longer works; the new one does.
    assert client.post("/api/auth/login", json={"email": "ceo@test.invalid", "password": "aStrongCeoPassw0rd!"}).status_code == 401
    relogin = client.post("/api/auth/login", json={"email": "ceo@test.invalid", "password": "aBrandNewCeoPassw0rd!"})
    assert relogin.status_code == 200
    assert relogin.get_json()["user"]["must_change_password"] is False
