"""Retenção dos backups guardados e limpeza da quarentena."""

import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.core.security import utcnow
from app.models import Backup, BackupStatus, Client, VerifyStatus
from app.services import storage
from app.services.ingest import refresh_client_stats

QUARANTINE_KEEP_DAYS = 30


def _is_restorable(b: Backup) -> bool:
    return b.status in (BackupStatus.ok, BackupStatus.warning) and b.verify_status != VerifyStatus.failed


def delete_backup_files(b: Backup) -> None:
    if b.storage_path:
        try:
            storage.remove_tree(storage.safe_child(storage.root(), *b.storage_path.split("/")))
        except (ValueError, OSError) as exc:
            logger.error("retention_delete_failed", backup=b.id, error=str(exc))
            raise
    b.deleted_at = utcnow()


def apply_client(db: Session, client: Client) -> int:
    rows = list(
        db.execute(
            select(Backup)
            .where(Backup.client_id == client.id, Backup.deleted_at.is_(None),
                   Backup.storage_path.is_not(None))
            .order_by(Backup.received_at.desc())
        ).scalars()
    )
    # Os N backups restauráveis mais recentes ficam SEMPRE, mesmo vencidos —
    # um cliente parado não pode ficar sem nenhum backup por causa da retenção.
    keep = {b.id for b in [r for r in rows if _is_restorable(r)][: client.retention_min_keep]}
    cutoff = utcnow() - timedelta(days=client.retention_days)
    removed = 0
    for b in rows:
        if b.id in keep:
            continue
        if (b.finished_at or b.received_at) < cutoff:
            try:
                delete_backup_files(b)
                removed += 1
            except (ValueError, OSError):
                continue
    if removed:
        refresh_client_stats(db, client)
        logger.info("retention_applied", client=client.slug, removed=removed)
    db.commit()
    return removed


def apply_all(db: Session) -> int:
    total = 0
    for client in db.execute(select(Client)).scalars().all():
        total += apply_client(db, client)
    return total


def purge_quarantine() -> None:
    q = storage.quarantine()
    if not q.is_dir():
        return
    cutoff = time.time() - QUARANTINE_KEEP_DAYS * 86400
    for client_dir in q.iterdir():
        if not client_dir.is_dir():
            continue
        for entry in client_dir.iterdir():
            try:
                if entry.lstat().st_mtime < cutoff:
                    storage.remove_tree(entry)
            except OSError:
                pass
