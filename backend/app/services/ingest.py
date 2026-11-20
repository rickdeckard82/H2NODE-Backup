"""Recepção dos uploads: incoming/<cliente>/<execução>/ -> store/<cliente>/<execução>/.

O agente envia primeiro os arquivos cifrados e por ÚLTIMO o manifest.json (o
rsync grava num temporário e renomeia, então o manifesto aparece de forma
atômica). Diretório com manifesto = upload completo, pronto para conferir.
"""

import hashlib
import os
import time
from datetime import timedelta
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.core.security import utcnow
from app.models import Backup, BackupComponent, BackupStatus, Client, VerifyStatus
from app.services import storage
from app.services.manifest import MANIFEST_MAX_BYTES, MANIFEST_NAME, Manifest

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def refresh_client_stats(db: Session, client: Client) -> None:
    client.stored_bytes = db.execute(
        select(func.coalesce(func.sum(Backup.size_bytes), 0)).where(
            Backup.client_id == client.id,
            Backup.deleted_at.is_(None),
            Backup.storage_path.is_not(None),
        )
    ).scalar_one()


def _quarantine(client: Client, run_dir: Path) -> str:
    ts = utcnow().strftime("%Y%m%dT%H%M%S")
    qdir = storage.quarantine() / client.slug
    qdir.mkdir(parents=True, exist_ok=True)
    dest = qdir / f"{run_dir.name[:80]}-{ts}"
    os.rename(run_dir, dest)
    return str(dest.relative_to(storage.root()))


def _reject(db: Session, client: Client, run_dir: Path, reason: str,
            manifest: Manifest | None = None) -> None:
    """Upload inválido: move para a quarentena e registra como execução com falha
    (aparece no painel — melhor do que sumir em silêncio)."""
    try:
        where = _quarantine(client, run_dir)
    except OSError as exc:
        where = f"(não foi possível mover: {exc})"
        storage.remove_tree(run_dir)
    logger.warning("ingest_rejected", client=client.slug, run=run_dir.name, reason=reason)
    now = utcnow()
    db.add(
        Backup(
            client_id=client.id,
            run_name=f"{run_dir.name[:60]}-rej{now.strftime('%H%M%S')}",
            status=BackupStatus.failed,
            agent_status=manifest.status if manifest else None,
            started_at=manifest.started_at if manifest else None,
            finished_at=manifest.finished_at if manifest else now,
            received_at=now,
            storage_path=None,
            error_message=f"{reason} — arquivos em quarentena: {where}",
            verify_status=VerifyStatus.skipped,
        )
    )
    client.last_backup_at = now
    client.last_status = BackupStatus.failed.value
    db.commit()


def _backup_status(m: Manifest, corrupted: bool) -> BackupStatus:
    if corrupted:
        return BackupStatus.corrupted
    if m.status == "failed" or any(c.status == "failed" for c in m.components):
        return BackupStatus.failed
    if m.status == "partial" or any(c.status == "warning" for c in m.components) or m.errors:
        return BackupStatus.warning
    return BackupStatus.ok


def ingest_run(db: Session, client: Client, run_dir: Path) -> Backup | None:
    mpath = run_dir / MANIFEST_NAME
    try:
        if mpath.is_symlink() or mpath.stat().st_size > MANIFEST_MAX_BYTES:
            raise ValueError("manifesto grande demais ou link simbólico")
        manifest = Manifest.model_validate_json(mpath.read_bytes())
    except (ValidationError, ValueError, OSError) as exc:
        _reject(db, client, run_dir, f"manifesto inválido: {str(exc)[:500]}")
        return None

    if manifest.client_id != client.slug:
        _reject(db, client, run_dir,
                f"manifesto é do cliente '{manifest.client_id}', mas chegou na pasta de '{client.slug}'",
                manifest)
        return None
    if manifest.run_name != run_dir.name:
        _reject(db, client, run_dir, "run_name do manifesto não confere com a pasta", manifest)
        return None
    if db.execute(
        select(Backup.id).where(Backup.client_id == client.id, Backup.run_name == manifest.run_name)
    ).first():
        _reject(db, client, run_dir, "execução duplicada (run_name já recebido)", manifest)
        return None

    files = [c.file for c in manifest.components if c.file]
    if len(files) != len(set(files)):
        _reject(db, client, run_dir, "manifesto lista o mesmo arquivo mais de uma vez", manifest)
        return None

    # Confere cada arquivo: existe, é arquivo regular, tamanho e SHA-256 do
    # conteúdo cifrado batem com o que o agente calculou antes de enviar.
    problems: dict[str, str] = {}
    for comp in manifest.components:
        if not comp.file:
            continue
        try:
            p = storage.safe_child(run_dir, comp.file)
        except ValueError as exc:
            problems[comp.file] = str(exc)
            continue
        if p.is_symlink() or not p.is_file():
            problems[comp.file] = "arquivo ausente no upload"
            continue
        size = p.stat().st_size
        if size != comp.size:
            problems[comp.file] = f"tamanho {size} ≠ {comp.size} informado pelo agente"
            continue
        if comp.sha256 and sha256_file(p) != comp.sha256:
            problems[comp.file] = "SHA-256 do arquivo cifrado não confere (corrompido na transferência?)"

    # Sobras (ex.: pasta .rsync-partial de envio interrompido) não entram no store.
    expected = set(files) | {MANIFEST_NAME}
    for entry in run_dir.iterdir():
        if entry.name not in expected:
            storage.remove_tree(entry)

    dest = storage.safe_child(storage.store(), client.slug, manifest.run_name)
    if dest.exists():
        _reject(db, client, run_dir, "destino já existe no armazenamento", manifest)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.rename(run_dir, dest)

    corrupted = bool(problems)
    status = _backup_status(manifest, corrupted)
    backup = Backup(
        client_id=client.id,
        run_name=manifest.run_name,
        status=status,
        agent_status=manifest.status,
        started_at=manifest.started_at,
        finished_at=manifest.finished_at,
        received_at=utcnow(),
        size_bytes=sum(c.size for c in manifest.components if c.file),
        plain_size_bytes=sum(c.plain_size for c in manifest.components if c.file),
        storage_path=str(dest.relative_to(storage.root())),
        agent_version=manifest.agent_version,
        manifest=manifest.model_dump(mode="json"),
        error_message="; ".join(manifest.errors)[:4000] or None,
    )
    if corrupted:
        backup.verify_status = VerifyStatus.failed
        backup.verify_mode = "integrity"
        backup.verified_at = utcnow()
        backup.verify_message = "; ".join(f"{k}: {v}" for k, v in problems.items())[:4000]
    elif files:
        backup.verify_status = VerifyStatus.pending
    else:
        backup.verify_status = VerifyStatus.skipped
        backup.verify_message = "nenhum arquivo para verificar"

    for i, comp in enumerate(manifest.components):
        bc = BackupComponent(
            position=i, kind=comp.kind, name=comp.name, file_name=comp.file,
            size_bytes=comp.size, sha256=comp.sha256, plain_size_bytes=comp.plain_size,
            plain_sha256=comp.plain_sha256, status=comp.status, message=comp.message,
            duration_seconds=comp.duration_s,
        )
        if comp.file and comp.file in problems:
            bc.verify_status = "failed"
            bc.verify_message = problems[comp.file]
        backup.components.append(bc)
    db.add(backup)

    client.last_backup_at = manifest.finished_at or utcnow()
    client.last_status = status.value
    client.hostname = manifest.hostname or client.hostname
    client.os_info = manifest.os or client.os_info
    client.agent_version = manifest.agent_version or client.agent_version
    db.flush()
    refresh_client_stats(db, client)
    db.commit()
    logger.info("ingest_ok", client=client.slug, run=manifest.run_name, status=status.value,
                size=backup.size_bytes)
    return backup


def scan(db: Session) -> int:
    """Varre incoming/ e processa todos os uploads completos. Devolve quantos."""
    storage.ensure_layout()
    clients = {c.slug: c for c in db.execute(select(Client)).scalars()}
    stale_before = time.time() - timedelta(hours=settings.incoming_stale_hours).total_seconds()
    n = 0
    for client_dir in sorted(storage.incoming().iterdir()):
        if client_dir.is_symlink() or not client_dir.is_dir():
            continue
        client = clients.get(client_dir.name)
        if client is None:
            continue
        for run_dir in sorted(client_dir.iterdir()):
            if run_dir.name.startswith("."):
                # ".h2node-test" é criado pelo `h2node-backup-agent test`
                # (".pulse-test" pelos agentes anteriores ao rebranding)
                if run_dir.name in (".h2node-test", ".pulse-test"):
                    storage.remove_tree(run_dir)
                continue
            try:
                if run_dir.is_symlink() or not run_dir.is_dir():
                    # arquivo solto na raiz da pasta do cliente: não é do protocolo
                    if run_dir.lstat().st_mtime < stale_before:
                        storage.remove_tree(run_dir)
                    continue
                if (run_dir / MANIFEST_NAME).exists():
                    ingest_run(db, client, run_dir)
                    n += 1
                elif run_dir.stat().st_mtime < stale_before:
                    _reject(db, client, run_dir,
                            f"upload incompleto: sem manifest.json após {settings.incoming_stale_hours}h")
            except Exception as exc:  # um upload ruim não pode travar a fila
                db.rollback()
                logger.error("ingest_error", client=client.slug, run=run_dir.name, error=str(exc))
    return n
