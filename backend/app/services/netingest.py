"""Recepção das configurações de equipamentos de rede (fila netin/ dos receptores).

Para cada arquivo pronto (`<nome>` + `<nome>.meta.json`):
  1. valida o conteúdo conforme o fabricante (netconfig.check);
  2. CIFRA com a chave pública GPG (os receptores FTP/TFTP recebem em claro —
     limitação dos protocolos) e grava em store/<equipamento>/<execução>/;
  3. apaga o original em claro e registra um Backup com um componente "config";
  4. a verificação profunda segue o caminho normal (decifra e revalida).
"""

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.core.security import utcnow
from app.models import Backup, BackupComponent, BackupStatus, Client, VerifyStatus
from app.services import netconfig, receivers, storage
from app.services.ingest import refresh_client_stats, sha256_file

_SESSION_STALE_SECONDS = 24 * 3600
_TMP_STALE_SECONDS = 3600


class NoPublicKey(RuntimeError):
    pass


def _encrypt(src: Path, dest: Path) -> None:
    pub = settings.backup_public_key_path
    if not Path(pub).is_file():
        raise NoPublicKey("chave pública GPG ausente")
    with tempfile.TemporaryDirectory(prefix="pb-enc-") as home:
        r = subprocess.run(
            ["gpg", "--homedir", home, "--batch", "--quiet", "--no-tty", "--yes",
             "--trust-model", "always", "--compress-algo", "none", "--cipher-algo", "AES256",
             "--recipient-file", pub, "--output", str(dest), "--encrypt", str(src)],
            capture_output=True, timeout=300, check=False,
        )
    if r.returncode != 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError("gpg falhou: " + r.stderr.decode(errors="replace")[-300:])


def _previous_plain_sha(db: Session, client: Client) -> str | None:
    return db.execute(
        select(BackupComponent.plain_sha256)
        .join(Backup, Backup.id == BackupComponent.backup_id)
        .where(Backup.client_id == client.id, BackupComponent.kind == "config")
        .order_by(Backup.received_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def ingest_file(db: Session, client: Client, data_path: Path, meta: dict) -> Backup:
    raw = data_path.read_bytes()
    plain_sha = hashlib.sha256(raw).hexdigest()
    res = netconfig.check(raw, client.vendor)
    same = res.ok and _previous_plain_sha(db, client) == plain_sha

    received = meta.get("received_at")
    try:
        when = datetime.fromisoformat(received).astimezone(UTC).replace(tzinfo=None) if received else utcnow()
    except ValueError:
        when = utcnow()
    run_name = f"{when.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    dest_dir = storage.safe_child(storage.store(), client.slug, run_name)
    dest_dir.mkdir(parents=True, mode=0o700)
    original = data_path.name.split("__", 1)[-1]
    enc_name = f"01-config-{receivers.safe_filename(original)}.gpg"
    enc_path = dest_dir / enc_name
    try:
        _encrypt(data_path, enc_path)
    except BaseException:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    proto = str(meta.get("protocol", "?")).upper()
    origin = f"recebido via {proto} de {meta.get('source_ip', '?')} ({meta.get('remote_path', original)})"
    message = f"{origin} — {res.message}" + (" — idêntica ao backup anterior" if same else "")
    status = BackupStatus.ok if res.ok else BackupStatus.failed
    manifest = {
        "format": "pulse-backup/net-1",
        "client_id": client.slug,
        "run_name": run_name,
        "protocol": meta.get("protocol"),
        "source_ip": meta.get("source_ip"),
        "remote_path": meta.get("remote_path"),
        "status": "success" if res.ok else "failed",
        "unchanged": same,
        "errors": [] if res.ok else [res.message],
    }
    (dest_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    backup = Backup(
        client_id=client.id, run_name=run_name, status=status,
        agent_status=manifest["status"], started_at=when, finished_at=when, received_at=utcnow(),
        size_bytes=enc_path.stat().st_size, plain_size_bytes=len(raw),
        storage_path=str(dest_dir.relative_to(storage.root())),
        agent_version=f"{proto.lower()}-receiver", manifest=manifest,
        error_message=None if res.ok else res.message,
        verify_status=VerifyStatus.pending,
    )
    backup.components.append(
        BackupComponent(
            position=0, kind="config", name=original, file_name=enc_name,
            size_bytes=enc_path.stat().st_size, sha256=sha256_file(enc_path),
            plain_size_bytes=len(raw), plain_sha256=plain_sha,
            status="ok" if res.ok else "failed", message=message[:2000], item_count=res.lines,
        )
    )
    db.add(backup)
    client.last_backup_at = when
    client.last_status = status.value
    db.flush()
    refresh_client_stats(db, client)
    db.commit()
    logger.info("net_ingest_ok", device=client.slug, file=original, ok=res.ok, unchanged=same)
    return backup


def scan(db: Session) -> int:
    base = receivers.netin()
    if not base.is_dir():
        return 0
    clients = {
        c.slug: c for c in db.execute(select(Client).where(Client.kind == "network")).scalars()
    }
    n = 0
    for dev_dir in sorted(base.iterdir()):
        if dev_dir.name.startswith(".") or not dev_dir.is_dir() or dev_dir.is_symlink():
            continue
        client = clients.get(dev_dir.name)
        for meta_path in sorted(dev_dir.glob("*" + receivers.META_SUFFIX)):
            data_path = meta_path.with_name(meta_path.name[: -len(receivers.META_SUFFIX)])
            try:
                if client is None:
                    raise LookupError(f"equipamento '{dev_dir.name}' não cadastrado")
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if data_path.is_symlink() or not data_path.is_file():
                    raise FileNotFoundError("arquivo de dados ausente")
                ingest_file(db, client, data_path, meta)
                n += 1
            except NoPublicKey:
                logger.error("net_ingest_no_public_key", device=dev_dir.name)
                return n  # mantém na fila até a chave existir
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.error("net_ingest_error", device=dev_dir.name, file=data_path.name, error=str(exc))
            # o original em claro nunca fica: processado ou descartado
            data_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
    return n


def cleanup() -> None:
    """Remove sessões FTP e temporários TFTP abandonados (conexões que caíram)."""
    now = time.time()
    for path, limit in ((receivers.netin() / ".sessions", _SESSION_STALE_SECONDS),
                        (receivers.netin() / ".tmp", _TMP_STALE_SECONDS)):
        if not path.is_dir():
            continue
        for entry in path.rglob("*"):
            try:
                if entry.is_file() and now - entry.stat().st_mtime > limit:
                    entry.unlink()
            except OSError:
                pass
        for d in sorted((p for p in path.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
            try:
                if now - d.stat().st_mtime > limit:
                    d.rmdir()
            except OSError:
                pass


def ensure_layout() -> None:
    for d in (receivers.netin(), receivers.netin() / ".sessions", receivers.netin() / ".tmp"):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
