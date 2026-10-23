"""Sinal de vida do worker: vem durante tarefas longas e diz o que ele está fazendo."""

from datetime import timedelta

from app import worker
from app.core.security import utcnow
from app.models import WorkerStatus


class _Keyring:
    available = True
    error = None


def test_heartbeat_records_current_task(db):
    with worker.task("verificando whm-cpanel/20261023T010002Z-beefbe"):
        worker.heartbeat(db, _Keyring())
        row = db.get(WorkerStatus, 1)
        assert row.busy_with == "verificando whm-cpanel/20261023T010002Z-beefbe"
        assert utcnow() - row.busy_since < timedelta(seconds=5)
    worker.heartbeat(db, _Keyring())  # ocioso
    row = db.get(WorkerStatus, 1)
    assert row.busy_with is None and row.busy_since is None


def test_task_is_cleared_on_error(db):
    try:
        with worker.task("aplicando a retenção"):
            raise RuntimeError("falhou")
    except RuntimeError:
        pass
    assert worker.current_task() is None


def test_monitoring_and_dashboard_show_busy_worker(auth_client, seeded):
    seeded.add(WorkerStatus(id=1, last_seen_at=utcnow() - timedelta(seconds=20), deep_verify=True,
                            busy_with="verificando whm-cpanel/r1", busy_since=utcnow() - timedelta(hours=3)))
    seeded.commit()
    tok = auth_client.post("/api/monitoring/token").json()["token"]
    w = auth_client.get("/api/monitoring/status", headers={"Authorization": f"Bearer {tok}"}).json()["worker"]
    assert w["busy_with"] == "verificando whm-cpanel/r1" and 3 * 3600 - 60 < w["busy_age"] < 3 * 3600 + 60
    assert w["last_seen_age"] < 60
    d = auth_client.get("/api/dashboard").json()["worker"]
    assert d["online"] is True and d["busy_with"] == "verificando whm-cpanel/r1"
