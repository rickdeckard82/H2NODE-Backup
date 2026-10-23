"""2FA: "lembrar este dispositivo" dispensa só o código, por TRUSTED_DEVICE_DAYS, no mesmo
navegador e para a mesma conta; cai ao trocar a senha, desativar o 2FA ou esquecer."""

from datetime import timedelta

import pyotp
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import utcnow
from app.main import app
from app.models import AuditLog, SystemRole, TrustedDevice
from app.services import trusted_devices
from tests.conftest import ADMIN_PW
from tests.test_security import _with_mfa

COOKIE = trusted_devices.COOKIE


def _login(client, username: str = "operador", password: str = ADMIN_PW) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _verify(client, token: str, secret: str, remember: bool) -> None:
    r = client.post("/api/auth/mfa/verify",
                    json={"mfa_token": token, "code": pyotp.TOTP(secret).now(), "remember_device": remember})
    assert r.status_code == 200, r.text
    client.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})


def test_remember_device_skips_only_the_code(client, seeded):
    secret = _with_mfa(seeded, "operador", SystemRole.operator)
    first = _login(client)
    assert first["mfa_required"] and first["remember_device_days"] == 30
    _verify(client, first["mfa_token"], secret, remember=True)
    assert client.cookies.get(COOKIE)
    row = seeded.query(TrustedDevice).one()
    assert row.token_hash != client.cookies.get(COOKIE)  # só o hash no banco
    assert timedelta(days=29) < row.expires_at - utcnow() <= timedelta(days=30)

    client.post("/api/auth/logout")
    again = _login(client)
    assert again["mfa_required"] is False and again["user"]["username"] == "operador"
    log = seeded.query(AuditLog).filter(AuditLog.action == "login").order_by(AuditLog.id.desc()).first()
    assert "dispositivo lembrado" in (log.after_json or "")

    # a senha continua obrigatória
    r = client.post("/api/auth/login", json={"username": "operador", "password": "errada"})
    assert r.status_code == 401


def test_without_remember_still_asks(client, seeded):
    secret = _with_mfa(seeded, "operador", SystemRole.operator)
    _verify(client, _login(client)["mfa_token"], secret, remember=False)
    assert client.cookies.get(COOKIE) is None
    client.post("/api/auth/logout")
    assert _login(client)["mfa_required"] is True


def test_cookie_is_per_account_and_expires(client, seeded):
    secret = _with_mfa(seeded, "operador", SystemRole.operator)
    _with_mfa(seeded, "outro", SystemRole.operator)
    _verify(client, _login(client)["mfa_token"], secret, remember=True)
    client.post("/api/auth/logout")
    assert _login(client, "outro")["mfa_required"] is True  # cookie de outra conta não vale
    row = seeded.query(TrustedDevice).one()
    row.expires_at = utcnow() - timedelta(minutes=1)
    seeded.commit()
    assert _login(client)["mfa_required"] is True


def test_other_browser_still_asks(client, seeded):
    secret = _with_mfa(seeded, "operador", SystemRole.operator)
    _verify(client, _login(client)["mfa_token"], secret, remember=True)
    with TestClient(app) as other:
        assert _login(other)["mfa_required"] is True


def test_password_change_and_forget_revoke(client, seeded):
    secret = _with_mfa(seeded, "operador", SystemRole.operator)
    _verify(client, _login(client)["mfa_token"], secret, remember=True)
    r = client.patch("/api/auth/me/password",
                     json={"current_password": ADMIN_PW, "new_password": "Nova-senha-123"})
    assert r.status_code == 200
    assert seeded.query(TrustedDevice).count() == 0
    client.post("/api/auth/logout")
    _verify(client, _login(client, password="Nova-senha-123")["mfa_token"], secret, remember=True)
    assert seeded.query(TrustedDevice).count() == 1
    r = client.post("/api/auth/mfa/trusted-devices/forget")
    assert r.status_code == 200 and seeded.query(TrustedDevice).count() == 0
    client.post("/api/auth/logout")
    assert _login(client, password="Nova-senha-123")["mfa_required"] is True


def test_option_disabled(client, seeded, monkeypatch):
    monkeypatch.setattr(settings, "trusted_device_days", 0)
    secret = _with_mfa(seeded, "operador", SystemRole.operator)
    first = _login(client)
    assert first["remember_device_days"] == 0
    _verify(client, first["mfa_token"], secret, remember=True)
    assert client.cookies.get(COOKIE) is None and seeded.query(TrustedDevice).count() == 0
