"""Recepção + verificação com gpg de verdade (a imagem do backend tem o gnupg)."""

import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
from datetime import timedelta
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.security import utcnow
from app.models import Backup, BackupStatus, Client, VerifyStatus
from app.services import gpg, ingest, retention, verify


def _gpg(home: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    r = subprocess.run(["gpg", "--homedir", str(home), "--batch", "--quiet", *args],
                       input=input_bytes, capture_output=True, check=True)
    return r.stdout


def _make_key(base: Path, name: str) -> tuple[Path, Path]:
    home = base / f"gnupg-{name}"
    home.mkdir(mode=0o700)
    # mesmo esquema do scripts/gen-backup-key.sh: primária só "cert" + subchave "encr"
    common = ("--rfc4880", "--passphrase", "", "--pinentry-mode", "loopback")
    _gpg(home, *common, "--quick-gen-key", f"{name} <{name}@test>", "rsa2048", "cert", "never")
    fpr = next(line.split(":")[9] for line in _gpg(home, "--with-colons", "--list-keys").decode().splitlines()
               if line.startswith("fpr:"))
    _gpg(home, *common, "--quick-add-key", fpr, "rsa2048", "encr", "never")
    pub = base / f"{name}.pub.asc"
    sec = base / f"{name}.sec.asc"
    pub.write_bytes(_gpg(home, "--armor", "--export"))
    sec.write_bytes(_gpg(home, "--armor", "--pinentry-mode", "loopback", "--passphrase", "",
                         "--export-secret-keys"))
    return pub, sec


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    base = tmp_path_factory.mktemp("keys")
    server = _make_key(base, "server")
    other = _make_key(base, "other")
    return {"server": server, "other": other, "base": base}


@pytest.fixture
def keyring(keys, monkeypatch):
    pub, sec = keys["server"]
    monkeypatch.setattr(settings, "backup_public_key_path", str(pub))
    monkeypatch.setattr(settings, "backup_private_key_path", str(sec))
    monkeypatch.setattr(settings, "backup_key_passphrase", None)
    kr = gpg.PrivateKeyring()
    kr.load()
    assert kr.available, kr.error
    return kr


def _encrypt(plain: bytes, pubkey: Path, tmp: Path) -> bytes:
    home = tmp / "enc-home"
    home.mkdir(mode=0o700, exist_ok=True)
    return _gpg(home, "--trust-model", "always", "--compress-algo", "none",
                "--recipient-file", str(pubkey), "--encrypt", input_bytes=plain)


def _tar_gz(files: dict[str, bytes]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue())


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def upload(slug: str, run: str, parts: list[tuple[str, str, str, bytes]], pubkey: Path,
           tmp: Path, status: str = "success", extra: dict | None = None) -> Path:
    """Simula o agente: grava os .gpg e o manifest.json em incoming/<slug>/<run>/."""
    d = Path(settings.storage_path) / "incoming" / slug / run
    d.mkdir(parents=True)
    comps = []
    for kind, name, fname, plain in parts:
        enc = _encrypt(plain, pubkey, tmp)
        (d / fname).write_bytes(enc)
        comps.append({"kind": kind, "name": name, "file": fname, "size": len(enc),
                      "sha256": _sha(enc), "plain_size": len(plain), "plain_sha256": _sha(plain),
                      "status": "ok", "duration_s": 1})
    m = {"format": "pulse-backup/1", "client_id": slug, "run_name": run, "agent_version": "1.0.0",
         "hostname": f"{slug}.local", "os": "Debian 12", "started_at": "2026-10-01T02:30:00Z",
         "finished_at": "2026-10-01T02:31:00Z", "status": status, "components": comps, "errors": []}
    if extra:
        m.update(extra)
    (d / "manifest.json").write_text(json.dumps(m))
    return d


GOOD_SQL = gzip.compress(b"-- MariaDB dump\nCREATE TABLE t (id int);\n-- Dump completed on 2026-10-01\n")
TRUNC_SQL = gzip.compress(
    b"--\n-- PostgreSQL database dump\n--\nCREATE TABLE t (id int);\nCOPY t FROM stdin;\n1\n"
)


@pytest.fixture
def web01(db):
    c = Client(slug="web01", name="Web 01")
    db.add(c)
    db.commit()
    return c


def test_ingest_and_deep_verify_ok(db, web01, keyring, keys, tmp_path):
    pub = keys["server"][0]
    tar = _tar_gz({"etc/hostname": b"web01\n", "etc/hosts": b"127.0.0.1 localhost\n"})
    upload("web01", "20261001T023000Z-aaaaaa", [
        ("files", "/etc", "01-files-etc.tar.gz.gpg", tar),
        ("mysql", "app", "02-mysql-app.sql.gz.gpg", GOOD_SQL),
    ], pub, tmp_path)

    assert ingest.scan(db) == 1
    b = db.query(Backup).one()
    assert b.status == BackupStatus.ok
    assert b.verify_status == VerifyStatus.pending
    assert (Path(settings.storage_path) / b.storage_path / "manifest.json").is_file()
    assert not (Path(settings.storage_path) / "incoming" / "web01" / "20261001T023000Z-aaaaaa").exists()
    assert web01.last_status == "ok" and web01.stored_bytes == b.size_bytes > 0

    verify.verify_backup(db, b, keyring)
    assert b.verify_status == VerifyStatus.ok, b.verify_message
    assert b.verify_mode == "full"
    files_comp = b.components[0]
    assert files_comp.item_count == 2


def test_truncated_dump_is_detected(db, web01, keyring, keys, tmp_path):
    upload("web01", "run-trunc", [("postgresql", "app", "01-postgresql-app.sql.gz.gpg", TRUNC_SQL)],
           keys["server"][0], tmp_path)
    ingest.scan(db)
    b = db.query(Backup).one()
    verify.verify_backup(db, b, keyring)
    assert b.verify_status == VerifyStatus.failed
    assert "marcador de fim" in b.verify_message
    assert b.status == BackupStatus.corrupted
    assert web01.last_status == "corrupted"


def test_wrong_recipient_key_is_detected(db, web01, keyring, keys, tmp_path):
    upload("web01", "run-other", [("mysql", "app", "01-mysql-app.sql.gz.gpg", GOOD_SQL)],
           keys["other"][0], tmp_path)
    ingest.scan(db)
    b = db.query(Backup).one()
    verify.verify_backup(db, b, keyring)
    assert b.verify_status == VerifyStatus.failed
    assert "outra chave" in b.verify_message


def test_integrity_mode_without_private_key(db, web01, keys, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_public_key_path", str(keys["server"][0]))
    upload("web01", "run-int", [("mysql", "app", "01-mysql-app.sql.gz.gpg", GOOD_SQL)],
           keys["server"][0], tmp_path)
    ingest.scan(db)
    b = db.query(Backup).one()
    verify.verify_backup(db, b, None)
    assert b.verify_status == VerifyStatus.ok
    assert b.verify_mode == "integrity"
    # corrompe um byte no disco: a reverificação acusa
    f = Path(settings.storage_path) / b.storage_path / "01-mysql-app.sql.gz.gpg"
    data = bytearray(f.read_bytes())
    data[-10] ^= 0xFF
    f.write_bytes(bytes(data))
    verify.verify_backup(db, b, None)
    assert b.verify_status == VerifyStatus.failed


def test_transfer_corruption_marks_corrupted(db, web01, keys, tmp_path):
    d = upload("web01", "run-bad", [("mysql", "app", "01-mysql-app.sql.gz.gpg", GOOD_SQL)],
               keys["server"][0], tmp_path)
    f = d / "01-mysql-app.sql.gz.gpg"
    data = bytearray(f.read_bytes())
    data[100] ^= 0x01
    f.write_bytes(bytes(data))
    ingest.scan(db)
    b = db.query(Backup).one()
    assert b.status == BackupStatus.corrupted
    assert b.verify_status == VerifyStatus.failed
    assert "SHA-256" in b.verify_message


def test_invalid_manifest_goes_to_quarantine(db, web01, keys, tmp_path):
    d = upload("web01", "run-x", [], keys["server"][0], tmp_path, extra={"client_id": "outro"})
    ingest.scan(db)
    b = db.query(Backup).one()
    assert b.status == BackupStatus.failed
    assert "outro" in b.error_message
    assert not d.exists()
    assert any((Path(settings.storage_path) / "quarantine" / "web01").iterdir())


def test_path_traversal_in_manifest_rejected(db, web01, keys, tmp_path):
    d = Path(settings.storage_path) / "incoming" / "web01" / "run-evil"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({
        "format": "pulse-backup/1", "client_id": "web01", "run_name": "run-evil", "status": "success",
        "components": [{"kind": "files", "name": "/", "file": "../../../etc/passwd.gpg", "status": "ok"}],
    }))
    ingest.scan(db)
    b = db.query(Backup).one()
    assert b.status == BackupStatus.failed
    assert "manifesto inválido" in b.error_message


def test_failed_component_and_stale_upload(db, web01, keys, tmp_path, monkeypatch):
    upload("web01", "run-part", [("mysql", "app", "01-mysql-app.sql.gz.gpg", GOOD_SQL)],
           keys["server"][0], tmp_path, status="partial",
           extra={"errors": ["postgresql x: pg_dump falhou"]})
    ingest.scan(db)
    assert db.query(Backup).one().status == BackupStatus.warning

    # upload sem manifesto e antigo => quarentena
    stale = Path(settings.storage_path) / "incoming" / "web01" / "run-stale"
    stale.mkdir()
    (stale / "x.gpg").write_bytes(b"x")
    old = utcnow().timestamp() - 48 * 3600
    os.utime(stale, (old, old))
    ingest.scan(db)
    rej = db.query(Backup).filter(Backup.run_name.like("run-stale%")).one()
    assert "incompleto" in rej.error_message


def test_retention_keeps_minimum(db, web01, keys, tmp_path):
    web01.retention_days = 1
    web01.retention_min_keep = 2
    db.commit()
    for i in range(4):
        upload("web01", f"run-{i}", [("mysql", "app", "01-mysql-app.sql.gz.gpg", GOOD_SQL)],
               keys["server"][0], tmp_path)
    ingest.scan(db)
    rows = db.query(Backup).order_by(Backup.run_name).all()
    for i, b in enumerate(rows):  # todos "antigos"; o run-3 é o mais recente
        b.received_at = utcnow() - timedelta(days=10 - i)
        b.finished_at = b.received_at
    db.commit()
    removed = retention.apply_client(db, web01)
    assert removed == 2
    alive = [b.run_name for b in rows if b.deleted_at is None]
    assert alive == ["run-2", "run-3"]
    assert not (Path(settings.storage_path) / rows[0].storage_path).exists()


def test_dashboard_and_backups_api(auth_client, seeded, keys, tmp_path):
    c = Client(slug="web01", name="Web 01")
    seeded.add(c)
    seeded.commit()
    upload("web01", "run-api", [("mysql", "app", "01-mysql-app.sql.gz.gpg", GOOD_SQL)],
           keys["server"][0], tmp_path)
    ingest.scan(seeded)

    d = auth_client.get("/api/dashboard", params={"days": 7}).json()
    assert d["clients_total"] == 1
    assert len(d["daily"]) == 7
    assert sum(p["ok"] for p in d["daily"]) == 1
    assert d["backups_bytes"] > 0

    page = auth_client.get("/api/backups").json()
    assert page["total"] == 1
    bid = page["items"][0]["id"]
    det = auth_client.get(f"/api/backups/{bid}").json()
    assert det["components"][0]["kind"] == "mysql"

    comp = det["components"][0]["id"]
    r = auth_client.get(f"/api/backups/{bid}/components/{comp}/download")
    assert r.status_code == 200 and len(r.content) == det["components"][0]["size_bytes"]

    assert auth_client.post(f"/api/backups/{bid}/verify").status_code == 200
    assert auth_client.delete(f"/api/backups/{bid}").status_code == 204
    assert auth_client.get("/api/backups").json()["total"] == 0
    assert auth_client.get("/api/clients").json()[0]["stored_bytes"] == 0


def test_worker_queue_verifies_pending(db, web01, keyring, keys, tmp_path):
    from app import worker

    upload("web01", "run-q", [("mysql", "app", "01-mysql-app.sql.gz.gpg", GOOD_SQL)],
           keys["server"][0], tmp_path)
    ingest.scan(db)
    assert worker.run_verifications(db, keyring) == 1
    b = db.query(Backup).one()
    assert b.verify_status == VerifyStatus.ok and b.verify_mode == "full"
    assert worker.next_pending(db) is None
    worker.heartbeat(db, keyring)
    worker.snapshot(db)


def test_file_kind_as_is_is_verified(db, web01, keyring, keys, tmp_path):
    """Backup de conta do cPanel: .tar.gz cifrado como está (kind "file")."""
    pub = keys["server"][0]
    acct = _tar_gz({"homedir/public_html/index.php": b"<?php echo 1;"})
    upload("web01", "run-file", [("file", "alfa.tar.gz", "01-file-alfa.tar.gz.gpg", acct)], pub, tmp_path)
    assert ingest.scan(db) == 1
    b = db.query(Backup).one()
    assert b.components[0].kind == "file"
    verify.verify_backup(db, b, keyring)
    assert b.verify_status == VerifyStatus.ok, b.verify_message
    assert b.verify_mode == "full"


def test_file_kind_truncated_gzip_is_detected(db, web01, keyring, keys, tmp_path):
    pub = keys["server"][0]
    acct = _tar_gz({"homedir/a": b"x" * 5000})
    upload("web01", "run-file-trunc", [("file", "beta.tar.gz", "01-file-beta.tar.gz.gpg", acct[:-20])],
           pub, tmp_path)
    ingest.scan(db)
    b = db.query(Backup).one()
    verify.verify_backup(db, b, keyring)
    assert b.verify_status == VerifyStatus.failed


def test_file_kind_non_gzip_checks_hash_only(db, web01, keyring, keys, tmp_path):
    pub = keys["server"][0]
    upload("web01", "run-file-bin", [("file", "dump.bin", "01-file-dump.bin.gpg", b"\x00binary" * 100)],
           pub, tmp_path)
    ingest.scan(db)
    b = db.query(Backup).one()
    verify.verify_backup(db, b, keyring)
    assert b.verify_status == VerifyStatus.ok, b.verify_message
