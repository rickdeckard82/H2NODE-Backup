from app.models import SystemRole, SystemUser
from tests.conftest import ADMIN_PW, login, make_user


def test_login_and_me(client):
    login(client)
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == "admin"
    assert r.json()["role"] == "admin"


def test_requires_login(client):
    assert client.get("/api/clients").status_code == 401
    assert client.get("/api/dashboard").status_code == 401


def test_wrong_password_and_lockout(client, seeded):
    for _ in range(5):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "errada"})
        assert r.status_code == 401
    # bloqueada: nem a senha certa entra
    r = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 429
    u = seeded.query(SystemUser).filter_by(username="admin").one()
    assert u.locked_until is not None


def test_unknown_user_same_error(client):
    r = client.post("/api/auth/login", json={"username": "ninguem", "password": "x"})
    assert r.status_code == 401
    assert r.json()["detail"] == "credenciais inválidas"


def test_csrf_required_on_mutations(client):
    login(client)
    client.headers.pop("X-CSRF-Token")
    r = client.post("/api/clients", json={"slug": "web01", "name": "Web"})
    assert r.status_code == 403


def test_role_hierarchy(client, seeded):
    make_user(seeded, "aud", SystemRole.auditor)
    login(client, "aud")
    assert client.get("/api/clients").status_code == 200
    assert client.post("/api/clients", json={"slug": "web01", "name": "Web"}).status_code == 403
    assert client.get("/api/system-users").status_code == 403
    assert client.get("/api/audit").status_code == 403


def test_cannot_demote_last_admin(auth_client, seeded):
    me = seeded.query(SystemUser).filter_by(username="admin").one()
    r = auth_client.patch(f"/api/system-users/{me.id}", json={"role": "operator"})
    assert r.status_code == 409


def test_change_password(auth_client):
    r = auth_client.patch("/api/auth/me/password",
                          json={"current_password": ADMIN_PW, "new_password": "nova-senha-longa-1"})
    assert r.status_code == 200
    auth_client.post("/api/auth/logout")
    login(auth_client, "admin", "nova-senha-longa-1")
