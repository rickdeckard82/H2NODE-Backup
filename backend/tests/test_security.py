"""Camadas de segurança do login: 2FA obrigatório por papel, falhas de 2FA contando para o
bloqueio e auditoria de toda falha de login."""

import pyotp

from app.core.config import settings
from app.core.crypto import encrypt
from app.models import AuditLog, SystemRole, SystemUser
from tests.conftest import ADMIN_PW, login, make_user


def _with_mfa(db, username: str, role: SystemRole) -> str:
    u = make_user(db, username, role)
    secret = pyotp.random_base32()
    u.mfa_secret, u.mfa_enabled = encrypt(secret), True
    db.commit()
    return secret


def _actions(db, username: str) -> list[tuple[str, str | None]]:
    rows = db.query(AuditLog).filter(AuditLog.actor_username == username).order_by(AuditLog.id).all()
    return [(r.action, r.after_json) for r in rows]


def test_mfa_failures_count_toward_lockout(client, seeded):
    secret = _with_mfa(seeded, "operador", SystemRole.operator)
    r = client.post("/api/auth/login", json={"username": "operador", "password": ADMIN_PW})
    assert r.json()["mfa_required"]
    token = r.json()["mfa_token"]
    for _ in range(5):
        r = client.post("/api/auth/mfa/verify", json={"mfa_token": token, "code": "000000"})
        assert r.status_code == 401
    # bloqueada: nem o código certo entra (e nem a senha, num login novo)
    r = client.post("/api/auth/mfa/verify", json={"mfa_token": token, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 429
    r = client.post("/api/auth/login", json={"username": "operador", "password": ADMIN_PW})
    assert r.status_code == 429
    acts = _actions(seeded, "operador")
    assert sum(1 for a, after in acts if a == "login_failed" and "2FA" in (after or "")) == 5
    assert any(a == "lockout" for a, _ in acts)


def test_failed_logins_are_audited(client, seeded):
    client.post("/api/auth/login", json={"username": "admin", "password": "errada"})
    client.post("/api/auth/login", json={"username": "fantasma", "password": "x"})
    admin = _actions(seeded, "admin")
    assert ("login_failed", '{"reason": "senha incorreta"}') in admin
    ghost = _actions(seeded, "fantasma")
    assert any(a == "login_failed" and "inexistente" in (after or "") for a, after in ghost)
    # login e logout bem-sucedidos também entram
    login(client)
    client.post("/api/auth/logout")
    acts = [a for a, _ in _actions(seeded, "admin")]
    assert "login" in acts and "logout" in acts


def test_mfa_required_for_admin_and_operator(client, seeded, monkeypatch):
    monkeypatch.setattr(settings, "mfa_required_roles", "admin,operator")
    make_user(seeded, "leitura", SystemRole.auditor)

    login(client)  # admin sem 2FA
    me = client.get("/api/auth/me").json()
    assert me["mfa_setup_required"] is True
    r = client.get("/api/clients")
    assert r.status_code == 403 and "2FA obrigatório" in r.json()["detail"]
    assert client.get("/api/downloads").status_code == 403

    # pode ativar o 2FA (e só isso)
    setup = client.post("/api/auth/mfa/setup").json()
    r = client.post("/api/auth/mfa/enable", json={"code": pyotp.TOTP(setup["secret"]).now()})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me").json()["mfa_setup_required"] is False
    assert client.get("/api/clients").status_code == 200

    # auditor não está na lista: entra sem 2FA
    client.cookies.clear()
    login(client, "leitura")
    assert client.get("/api/auth/me").json()["mfa_setup_required"] is False
    assert client.get("/api/clients").status_code == 200


def test_mfa_optional_when_setting_empty(auth_client, seeded, monkeypatch):
    monkeypatch.setattr(settings, "mfa_required_roles", "")
    assert auth_client.get("/api/auth/me").json()["mfa_setup_required"] is False
    assert auth_client.get("/api/clients").status_code == 200
    u = seeded.query(SystemUser).filter_by(username="admin").one()
    assert not u.mfa_enabled
