"""Recepção das configurações de equipamentos de rede (fila netin/ dos receptores).

Para cada arquivo pronto (`<nome>` + `<nome>.meta.json`):
  1. valida o conteúdo conforme o fabricante (netconfig.check) — ou, no tipo
     "Arquivos e bancos", conforme a extensão (filecheck.check_file);
  2. CIFRA com a chave pública GPG (os receptores FTP/TFTP recebem em claro —
     limitação dos protocolos) e grava em store/<equipamento>/<execução>/;
  3. apaga o original em claro e registra um Backup com um componente "config";
  4. a verificação profunda segue o caminho normal (decifra e revalida).
"""

import hashlib
import json
import os
import re
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
from app.services import filecheck, netconfig, receivers, storage
from app.services.ingest import refresh_client_stats, sha256_file

_SESSION_STALE_SECONDS = 24 * 3600
_TMP_STALE_SECONDS = 3600


class NoPublicKey(RuntimeError):
    pass


def _encrypt(data: bytes | Path, dest: Path) -> None:
    """Cifra `data` para a chave pública em `dest`: bytes vão em memória (stdin do gpg);
    um Path é lido pelo próprio gpg em streaming (arquivos de GB)."""
    pub = settings.backup_public_key_path
    if not Path(pub).is_file():
        raise NoPublicKey("chave pública GPG ausente")
    src = data if isinstance(data, Path) else None
    with tempfile.TemporaryDirectory(prefix="pb-enc-") as home:
        r = subprocess.run(
            ["gpg", "--homedir", home, "--batch", "--quiet", "--no-tty", "--yes",
             "--trust-model", "always", "--compress-algo", "none", "--cipher-algo", "AES256",
             "--recipient-file", pub, "--output", str(dest), "--encrypt", *([str(src)] if src else [])],
            input=None if src else data, capture_output=True, timeout=6 * 3600 if src else 300, check=False,
        )
    if r.returncode != 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError("gpg falhou: " + r.stderr.decode(errors="replace")[-300:])


_OLT_ID_MMDD = re.compile(r"^(\d{5,})_\d{4}$")
_DATE_SUFFIX = re.compile(r"[_.-]?\d{8}(?:[_.-]?\d{6})?$")


def name_key(name: str) -> str:
    """Nome sem a data final: `config_10.0.0.1_20261015` e `..._20261016` são o mesmo arquivo.
    Uma UNM2000 envia uma configuração por OLT; só se compara com a anterior da MESMA OLT."""
    m = _OLT_ID_MMDD.match(name)  # Fiberhome: <ID-da-OLT>_<MMDD>
    if m:
        return m.group(1)
    return _DATE_SUFFIX.sub("", name)


def _previous_content_sha(db: Session, client: Client, name: str,
                          kinds: tuple[str, ...] = ("config",)) -> str | None:
    key = name_key(name)
    rows = db.execute(
        select(BackupComponent.name, BackupComponent.plain_sha256, Backup.manifest)
        .join(Backup, Backup.id == BackupComponent.backup_id)
        .where(Backup.client_id == client.id, BackupComponent.kind.in_(kinds))
        .order_by(Backup.received_at.desc())
        .limit(500)
    ).all()
    for n, sha, manifest in rows:
        if name_key(n) == key:
            # content_sha256 desde a 0.7.0; antes era sempre o hash do arquivo inteiro
            return (manifest or {}).get("content_sha256") or sha
    return None


def ingest_file(db: Session, client: Client, data_path: Path, meta: dict) -> Backup:
    received = meta.get("received_at")
    try:
        when = datetime.fromisoformat(received).astimezone(UTC).replace(tzinfo=None) if received else utcnow()
    except ValueError:
        when = utcnow()
    proto = str(meta.get("protocol", "?"))
    original = data_path.name.split("__", 1)[-1]
    common = {"when": when, "protocol": proto, "source_ip": meta.get("source_ip"),
              "remote_path": meta.get("remote_path"), "agent_version": f"{proto.lower()}-receiver"}
    if client.vendor == FILES_VENDOR:
        return store_upload(db, client, data_path, original, **common)
    return store_config(db, client, data_path.read_bytes(), original, **common)


def store_config(
    db: Session, client: Client, raw: bytes, original: str, *, when: datetime, protocol: str,
    source_ip: str | None, remote_path: str | None, agent_version: str,
) -> Backup:
    """Valida, cifra e registra uma configuração de equipamento (recebida por FTP/TFTP
    ou coletada por SSH). `raw` só existe em memória; no disco fica só o .gpg."""
    content_sha = netconfig.content_sha256(raw, client.vendor)
    res = netconfig.check(raw, client.vendor)
    same = res.ok and _previous_content_sha(db, client, original) == content_sha
    return _store(
        db, client, raw, original, kind="config", status="ok" if res.ok else "failed",
        check_message=res.message, items=res.lines, plain_size=len(raw),
        plain_sha=hashlib.sha256(raw).hexdigest(), content_sha=content_sha, same=same, when=when,
        protocol=protocol, source_ip=source_ip, remote_path=remote_path, agent_version=agent_version,
    )


# Tipo "Arquivos e bancos": dumps .sql, .zip, .conf… enviados por FTP por um servidor/serviço.
FILES_VENDOR = receivers.FILES_VENDOR
FILE_KINDS = ("file", "mysql", "postgresql")


def store_upload(
    db: Session, client: Client, path: Path, original: str, *, when: datetime, protocol: str,
    source_ip: str | None, remote_path: str | None, agent_version: str,
) -> Backup:
    """Testa, cifra e registra um arquivo do tipo "Arquivos e bancos". Pode ter GB: é testado
    e cifrado direto do disco, em streaming (quem apaga o original em claro é o scan)."""
    res = filecheck.check_file(path, original)
    plain_sha = sha256_file(path)
    same = res.ok and _previous_content_sha(db, client, original, FILE_KINDS) == plain_sha
    return _store(
        db, client, path, original, kind=res.kind, status=res.status, check_message=res.message,
        items=res.items, plain_size=path.stat().st_size, plain_sha=plain_sha, content_sha=plain_sha,
        same=same, when=when, protocol=protocol, source_ip=source_ip, remote_path=remote_path,
        agent_version=agent_version,
    )


def _store(
    db: Session, client: Client, src: bytes | Path, original: str, *, kind: str, status: str,
    check_message: str, items: int | None, plain_size: int, plain_sha: str, content_sha: str, same: bool,
    when: datetime, protocol: str, source_ip: str | None, remote_path: str | None, agent_version: str,
) -> Backup:
    run_name = f"{when.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    dest_dir = storage.safe_child(storage.store(), client.slug, run_name)
    dest_dir.mkdir(parents=True, mode=0o700)
    enc_name = f"01-{kind}-{receivers.safe_filename(original)}.gpg"
    enc_path = dest_dir / enc_name
    try:
        _encrypt(src, enc_path)
    except BaseException:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise

    proto = protocol.upper()
    if protocol == "ssh":
        origin = f"coletado via SSH de {source_ip or '?'} ({remote_path or original})"
    else:
        origin = f"recebido via {proto} de {source_ip or '?'} ({remote_path or original})"
    unchanged = " — idêntica ao backup anterior" if kind == "config" else " — idêntico ao backup anterior"
    message = f"{origin} — {check_message}" + (unchanged if same else "")
    failed = status == "failed"
    manifest = {
        "format": "pulse-backup/net-1",
        "client_id": client.slug,
        "run_name": run_name,
        "protocol": protocol,
        "source_ip": source_ip,
        "remote_path": remote_path,
        "status": "failed" if failed else "success",
        "unchanged": same,
        "content_sha256": content_sha,
        "errors": [] if status == "ok" else [check_message],
    }
    (dest_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    backup = Backup(
        client_id=client.id, run_name=run_name, status=BackupStatus(status),
        agent_status=manifest["status"], started_at=when, finished_at=when, received_at=utcnow(),
        size_bytes=enc_path.stat().st_size, plain_size_bytes=plain_size,
        storage_path=str(dest_dir.relative_to(storage.root())),
        agent_version=agent_version, manifest=manifest,
        error_message=None if status == "ok" else check_message,
        verify_status=VerifyStatus.pending,
    )
    backup.components.append(
        BackupComponent(
            position=0, kind=kind, name=original, file_name=enc_name,
            size_bytes=enc_path.stat().st_size, sha256=sha256_file(enc_path),
            plain_size_bytes=plain_size, plain_sha256=plain_sha,
            status=status, message=message[:2000], item_count=items,
        )
    )
    db.add(backup)
    client.last_backup_at = when
    client.last_status = status
    db.flush()
    refresh_client_stats(db, client)
    db.commit()
    logger.info("net_ingest_ok", device=client.slug, file=original, kind=kind, status=status, unchanged=same)
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
