"""Worker de background (container próprio, mesma imagem do backend).

Ciclo a cada WORKER_POLL_SECONDS:
  1. recebe os uploads completos de incoming/ (agente Linux) e de netin/
     (configurações de switches/roteadores via FTP/TFTP, cifradas aqui);
  2. verifica os backups pendentes (um por vez, FOR UPDATE SKIP LOCKED);
  3. de hora em hora: retenção, limpeza da quarentena, reverificação periódica;
  4. foto do disco a cada STORAGE_SNAPSHOT_MINUTES.

Uso: python -m app.worker
"""

import signal
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging, logger
from app.core.security import utcnow
from app.models import Backup, BackupStatus, Client, StorageSnapshot, VerifyStatus, WorkerStatus
from app.services import firmware, gpg, ingest, netingest, receivers, retention, sshkeys, storage, verify

_HOUSEKEEPING_EVERY = 3600
_VERIFY_BUDGET_SECONDS = 600  # devolve o controle ao ciclo (ingest) após isso
_SNAPSHOT_KEEP_DAYS = 400

_stop = False


def _on_signal(signum, _frame) -> None:  # noqa: ANN001
    global _stop
    _stop = True
    logger.info("worker_stopping", signal=signum)


# Sinal de vida: uma thread grava a cada HEARTBEAT_SECONDS, inclusive no meio de uma tarefa longa.
HEARTBEAT_SECONDS = 30
_task: tuple[str, datetime] | None = None
_task_lock = threading.Lock()


@contextmanager
def task(label: str):  # noqa: ANN201
    """Marca o que o worker está fazendo (aparece no painel e no monitoramento)."""
    global _task
    with _task_lock:
        _task = (label[:255], utcnow())
    try:
        yield
    finally:
        with _task_lock:
            _task = None


def current_task() -> tuple[str, datetime] | None:
    with _task_lock:
        return _task


def heartbeat(db, keyring: gpg.PrivateKeyring) -> None:
    row = db.get(WorkerStatus, 1)
    if row is None:
        row = WorkerStatus(id=1, last_seen_at=utcnow())
        db.add(row)
    row.last_seen_at = utcnow()
    row.deep_verify = keyring.available
    row.message = (keyring.error or "verificação profunda ativa")[:255]
    cur = current_task()
    row.busy_with, row.busy_since = cur if cur else (None, None)
    db.commit()


def _heartbeat_loop(keyring: gpg.PrivateKeyring) -> None:
    while not _stop:
        try:
            with SessionLocal() as db:
                heartbeat(db, keyring)
        except Exception as exc:  # noqa: BLE001  (o sinal nunca derruba o worker)
            logger.warning("worker_heartbeat_failed", error=str(exc))
        for _ in range(HEARTBEAT_SECONDS):
            if _stop:
                break
            time.sleep(1)


def prepare(db) -> None:
    """Estado consistente na partida: pastas dos clientes, authorized_keys e
    verificações que ficaram "running" num worker que morreu."""
    storage.ensure_layout()
    for c in db.execute(select(Client)).scalars():
        storage.ensure_client_dirs(c.slug)
    sshkeys.sync_authorized_keys(db)
    netingest.ensure_layout()
    firmware.ensure_layout()
    receivers.sync(db)
    db.execute(
        update(Backup).where(Backup.verify_status == VerifyStatus.running)
        .values(verify_status=VerifyStatus.pending)
    )
    db.commit()


def next_pending(db) -> Backup | None:
    # Trava só o id: o Backup carrega `client` por outer join, e o PostgreSQL não
    # aceita FOR UPDATE no lado anulável de um outer join.
    backup_id = db.execute(
        select(Backup.id)
        .where(Backup.verify_status == VerifyStatus.pending, Backup.deleted_at.is_(None))
        .order_by(Backup.received_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if backup_id is None:
        db.rollback()
        return None
    b = db.get(Backup, backup_id)
    assert b is not None
    b.verify_status = VerifyStatus.running
    db.commit()
    return b


def run_verifications(db, keyring: gpg.PrivateKeyring) -> int:
    started = time.monotonic()
    n = 0
    while not _stop and time.monotonic() - started < _VERIFY_BUDGET_SECONDS:
        b = next_pending(db)
        if b is None:
            break
        try:
            label = f"verificando {b.client.slug}/{b.run_name}" if b.client else f"verificando backup {b.id}"
            with task(label):
                verify.verify_backup(db, b, keyring)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("verify_error", backup=b.id, error=str(exc))
            b = db.get(Backup, b.id)
            if b is not None:
                b.verify_status = VerifyStatus.failed
                b.verify_message = f"erro interno na verificação: {exc}"[:2000]
                b.verified_at = utcnow()
                db.commit()
        n += 1
    return n


def schedule_reverify(db) -> int:
    days = settings.reverify_interval_days
    if days <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=days)
    res = db.execute(
        update(Backup)
        .where(
            Backup.deleted_at.is_(None),
            Backup.storage_path.is_not(None),
            Backup.verify_status == VerifyStatus.ok,
            Backup.verified_at < cutoff,
            Backup.status != BackupStatus.corrupted,
        )
        .values(verify_status=VerifyStatus.pending)
    )
    db.commit()
    return res.rowcount or 0


def snapshot(db) -> None:
    u = storage.disk_usage()
    backups_bytes = db.execute(
        select(func.coalesce(func.sum(Backup.size_bytes), 0)).where(
            Backup.deleted_at.is_(None), Backup.storage_path.is_not(None)
        )
    ).scalar_one()
    db.add(StorageSnapshot(taken_at=utcnow(), total_bytes=u.total, used_bytes=u.used,
                           free_bytes=u.free, backups_bytes=backups_bytes))
    db.query(StorageSnapshot).filter(
        StorageSnapshot.taken_at < utcnow() - timedelta(days=_SNAPSHOT_KEEP_DAYS)
    ).delete(synchronize_session=False)
    db.commit()


def main() -> None:
    configure_logging()
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    keyring = gpg.PrivateKeyring()
    keyring.load()
    logger.info("worker_started", deep_verify=keyring.available, note=keyring.error)

    with SessionLocal() as db:
        prepare(db)
    threading.Thread(target=_heartbeat_loop, args=(keyring,), name="heartbeat", daemon=True).start()

    last_housekeeping = 0.0
    last_snapshot = 0.0
    while not _stop:
        try:
            with SessionLocal() as db:
                # novos clientes cadastrados no painel desde o último ciclo
                for c in db.execute(select(Client)).scalars():
                    storage.ensure_client_dirs(c.slug)
                with task("recebendo backups dos agentes"):
                    ingest.scan(db)
                with task("recebendo e cifrando arquivos FTP/TFTP"):
                    netingest.scan(db)
                run_verifications(db, keyring)
                now = time.monotonic()
                if now - last_housekeeping >= _HOUSEKEEPING_EVERY:
                    with task("aplicando a retenção"):
                        retention.apply_all(db)
                        retention.purge_quarantine()
                        netingest.cleanup()
                    queued = schedule_reverify(db)
                    if queued:
                        logger.info("reverify_scheduled", count=queued)
                    last_housekeeping = now
                if now - last_snapshot >= settings.storage_snapshot_minutes * 60:
                    snapshot(db)
                    last_snapshot = now
        except Exception as exc:  # noqa: BLE001
            logger.error("worker_cycle_error", error=str(exc))
        for _ in range(settings.worker_poll_seconds):
            if _stop:
                break
            time.sleep(1)
    logger.info("worker_stopped")


if __name__ == "__main__":
    main()
