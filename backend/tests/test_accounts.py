"""Contas cPanel: só cópias reais (com arquivo) de servidores com agente."""

from datetime import timedelta

from app.core.security import utcnow
from app.models import Backup, BackupComponent, BackupStatus, Client


def _run(db, client: Client, run: str, age_days: int, parts: list[tuple[str, str | None, int, str]]) -> None:
    b = Backup(client_id=client.id, run_name=run, status=BackupStatus.ok,
               storage_path=f"store/{client.slug}/{run}", received_at=utcnow() - timedelta(days=age_days))
    db.add(b)
    db.flush()
    for pos, (name, file_name, size, st) in enumerate(parts):
        db.add(BackupComponent(backup_id=b.id, position=pos, kind="file", name=name, file_name=file_name,
                               size_bytes=size, status=st))


def test_accounts_only_real_copies_from_servers(auth_client, seeded):
    whm = Client(slug="whm", name="WHM/cPanel")
    erp = Client(slug="arquivos-erp", name="Arquivos ERP", kind="network", vendor="files",
                 mgmt_ip="192.0.2.30", protocol="ftp")
    seeded.add_all([whm, erp])
    seeded.flush()
    _run(seeded, whm, "r1", 3, [("abcs.tar.gz", "01-file-abcs.tar.gz.gpg", 1000, "ok"),
                                ("cliente2.tar.gz", "02-file-cliente2.tar.gz.gpg", 50, "ok")])
    # execução de hoje: padrão sem arquivo (data errada) e conta que o WHM não copiou — sem arquivo
    _run(seeded, whm, "r2", 0, [("/backup/cpanel/@today/accounts/*.tar.gz", None, 0, "failed"),
                                ("cliente2.tar.gz", None, 0, "failed")])
    _run(seeded, erp, "r1", 2, [("arquivos-erp-arquivos-20261020-190010", "01-file-x.gpg", 40, "ok")])
    seeded.commit()

    items = auth_client.get("/api/backups/accounts").json()["items"]
    assert [(a["name"], a["size_bytes"], a["versions"]) for a in items] == [
        ("abcs.tar.gz", 1000, 1),
        ("cliente2.tar.gz", 50, 1),  # a última cópia que existe, não a falha de hoje
    ]
    hist = auth_client.get("/api/backups/accounts/history",
                           params={"client_id": whm.id, "name": "cliente2.tar.gz"}).json()
    assert len(hist) == 1 and hist[0]["size_bytes"] == 50
