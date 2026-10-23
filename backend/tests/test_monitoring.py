"""Integração com Zabbix: GET /api/monitoring/status com token (pull), configurado no painel."""

from datetime import timedelta

from app.core.security import utcnow
from app.models import Backup, BackupStatus, Client, VerifyStatus, WorkerStatus

STATUS = "/api/monitoring/status"


def _token(auth_client) -> str:
    r = auth_client.post("/api/monitoring/token")
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    assert tok.startswith("pbm_") and r.json()["settings"]["configured"] is True
    return tok


def _get(client, token: str | None, ip: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if ip:
        headers["X-Forwarded-For"] = ip
    return client.get(STATUS, headers=headers)


def _seed(db) -> None:
    now = utcnow()
    ok = Client(slug="web1", name="Web 1", kind="server", expected_interval_hours=24,
                last_backup_at=now - timedelta(hours=2), last_status="ok")
    bad = Client(slug="sw-core", name="SW Core", kind="network", vendor="huawei", mgmt_ip="192.0.2.15",
                 protocol="ftp", expected_interval_hours=24, last_backup_at=now - timedelta(hours=1),
                 last_status="failed")
    late = Client(slug="db1", name="DB 1", kind="server", expected_interval_hours=24,
                  last_backup_at=now - timedelta(days=3), last_status="ok")
    never = Client(slug="novo", name="Novo", kind="server", expected_interval_hours=24)
    off = Client(slug="antigo", name="Antigo", kind="server", is_active=False)
    db.add_all([ok, bad, late, never, off])
    db.flush()
    db.add(Backup(client_id=ok.id, run_name="r1", status=BackupStatus.ok, size_bytes=1000,
                  verify_status=VerifyStatus.ok))
    db.add(Backup(client_id=bad.id, run_name="r1", status=BackupStatus.failed, size_bytes=10,
                  error_message="arquivo truncado:\n falta o return", verify_status=VerifyStatus.failed,
                  verify_message="x"))
    db.add(WorkerStatus(id=1, last_seen_at=now - timedelta(seconds=40), deep_verify=True))
    db.commit()


def test_status_disabled_until_token_exists(client, auth_client):
    assert _get(client, "qualquer").status_code == 404


def test_status_requires_valid_token(auth_client):
    tok = _token(auth_client)
    assert _get(auth_client, None).status_code == 401
    assert _get(auth_client, "pbm_errado").status_code == 401
    assert _get(auth_client, tok).status_code == 200
    # trocar o token invalida o anterior; revogar desliga o endpoint
    tok2 = _token(auth_client)
    assert _get(auth_client, tok).status_code == 401 and _get(auth_client, tok2).status_code == 200
    assert auth_client.delete("/api/monitoring/token").json()["configured"] is False
    assert _get(auth_client, tok2).status_code == 404


def test_status_payload(auth_client, seeded):
    _seed(seeded)
    tok = _token(auth_client)
    r = _get(auth_client, tok)
    assert r.status_code == 200, r.text
    data = r.json()
    by = {c["slug"]: c for c in data["clients"]}
    assert set(by) == {"web1", "sw-core", "db1", "novo"}  # inativo fica de fora (some do LLD)
    assert (by["web1"]["health"], by["web1"]["health_code"], by["web1"]["verify_code"]) == ("ok", 0, 0)
    assert by["web1"]["last_size"] == 1000 and 7000 < by["web1"]["last_backup_age"] < 7300
    assert (by["sw-core"]["health_code"], by["sw-core"]["verify_code"]) == (2, 2)
    assert by["sw-core"]["error"] == "arquivo truncado: falta o return"
    assert by["sw-core"]["vendor"] == "huawei"
    assert by["db1"]["health_code"] == 3
    assert (by["novo"]["health_code"], by["novo"]["last_backup_age"], by["novo"]["verify_code"]) == (4, -1, 3)
    assert data["summary"] == {"ok": 1, "warning": 0, "failed": 1, "overdue": 1, "never": 1}
    assert data["worker"]["deep_verify"] == 1 and 30 <= data["worker"]["last_seen_age"] < 120
    assert set(data["disk"]) == {"total", "used", "free", "pused"}
    s = auth_client.get("/api/monitoring/settings").json()
    assert s["last_used_at"] and s["token_hint"] == tok[-6:]
    assert s["status_url"].endswith("/api/monitoring/status")


def test_allowed_networks(auth_client):
    tok = _token(auth_client)
    r = auth_client.put("/api/monitoring/settings", json={"allowed_networks": ["198.51.100.10"]})
    assert r.status_code == 200 and r.json()["allowed_networks"] == ["198.51.100.10/32"]
    assert _get(auth_client, tok, ip="198.51.100.10").status_code == 200
    assert _get(auth_client, tok, ip="203.0.113.9").status_code == 403
    r = auth_client.put("/api/monitoring/settings", json={"allowed_networks": ["0.0.0.0/0"]})
    assert r.status_code == 422


def test_settings_admin_only(client, seeded):
    from app.models import SystemRole
    from tests.conftest import login, make_user

    make_user(seeded, "leitura", SystemRole.auditor)
    login(client, "leitura")
    assert client.get("/api/monitoring/settings").status_code == 403
    assert client.post("/api/monitoring/token").status_code == 403
