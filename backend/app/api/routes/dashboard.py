from collections import Counter
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_auditor
from app.core.db import get_db
from app.core.security import utcnow
from app.models import Backup, BackupStatus, Client, StorageSnapshot, SystemUser, VerifyStatus, WorkerStatus
from app.schemas.dashboard import (
    ClientSize,
    DailyPoint,
    DashboardOut,
    OverdueClient,
    RecentProblem,
    StoragePoint,
    WorkerInfo,
)
from app.services import storage
from app.services.health import client_health

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_FAILED = (BackupStatus.failed, BackupStatus.corrupted)


def _tz(user: SystemUser) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _bucket(status: BackupStatus) -> str:
    if status in _FAILED:
        return "failed"
    return status.value  # ok | warning


@router.get("", response_model=DashboardOut)
def dashboard(
    db: Session = Depends(get_db),
    user: SystemUser = Depends(require_auditor),
    days: int = Query(30, ge=7, le=365),
) -> DashboardOut:
    tz = _tz(user)
    now = utcnow()
    local_today = now.replace(tzinfo=UTC).astimezone(tz).date()
    first_day = local_today - timedelta(days=days - 1)
    # início do primeiro dia local, em UTC naive (como no banco)
    window_start = datetime.combine(first_day, time(), tz).astimezone(UTC).replace(tzinfo=None)

    def local_date(dt) -> str:  # noqa: ANN001
        return dt.replace(tzinfo=UTC).astimezone(tz).date().isoformat()

    # ---- clientes ----
    clients = list(db.execute(select(Client)).scalars())
    health = Counter(client_health(c) for c in clients)

    # ---- execuções na janela (por dia local) ----
    rows = db.execute(
        select(Backup.received_at, Backup.status, Backup.size_bytes)
        .where(Backup.received_at >= window_start)
    ).all()
    daily = {
        (first_day + timedelta(days=i)).isoformat(): DailyPoint(
            date=(first_day + timedelta(days=i)).isoformat()
        )
        for i in range(days)
    }
    window: Counter[str] = Counter()
    last24: Counter[str] = Counter()
    bytes_window = 0
    for received_at, st, size in rows:
        b = _bucket(st)
        window[b] += 1
        if now - received_at <= timedelta(hours=24):
            last24[b] += 1
        p = daily.get(local_date(received_at))
        if p is not None:
            setattr(p, b, getattr(p, b) + 1)
            p.bytes += size or 0
        bytes_window += size or 0
    total = sum(window.values())
    success_rate = (window["ok"] + window["warning"]) / total if total else None

    # ---- verificação (backups ainda guardados) ----
    ver = dict(
        db.execute(
            select(Backup.verify_status, func.count())
            .where(Backup.deleted_at.is_(None), Backup.storage_path.is_not(None))
            .group_by(Backup.verify_status)
        ).all()
    )
    verification = {v.value: int(ver.get(v, 0)) for v in VerifyStatus}

    # ---- disco ----
    disk = storage.disk_usage()
    backups_bytes = sum(c.stored_bytes for c in clients)
    snaps = db.execute(
        select(StorageSnapshot).where(StorageSnapshot.taken_at >= window_start)
        .order_by(StorageSnapshot.taken_at)
    ).scalars()
    by_day: dict[str, StoragePoint] = {}
    for s in snaps:  # fica a última foto de cada dia
        d = local_date(s.taken_at)
        by_day[d] = StoragePoint(date=d, used_bytes=s.used_bytes, free_bytes=s.free_bytes,
                                 backups_bytes=s.backups_bytes)

    top = sorted(clients, key=lambda c: c.stored_bytes, reverse=True)[:8]

    problems = db.execute(
        select(Backup)
        .where(or_(Backup.status.in_(_FAILED), Backup.verify_status == VerifyStatus.failed))
        .order_by(Backup.received_at.desc())
        .limit(8)
    ).scalars().unique()

    overdue = [
        OverdueClient(id=c.id, name=c.name, slug=c.slug, health=client_health(c),
                      last_backup_at=c.last_backup_at,
                      expected_interval_hours=c.expected_interval_hours)
        for c in clients
        if client_health(c) in ("overdue", "never")
    ]

    ws = db.get(WorkerStatus, 1)
    # sinal a cada 30 s (thread), inclusive durante tarefas longas: 5 min sem sinal = parado
    online = bool(ws and now - ws.last_seen_at <= timedelta(minutes=5))

    return DashboardOut(
        days=days,
        clients_total=len(clients),
        clients_active=sum(1 for c in clients if c.is_active),
        servers_active=sum(1 for c in clients if c.is_active and c.kind == "server"),
        devices_active=sum(1 for c in clients if c.is_active and c.kind == "network"),
        clients_health=dict(health),
        last24h={k: last24[k] for k in ("ok", "warning", "failed")},
        window={k: window[k] for k in ("ok", "warning", "failed")},
        success_rate=success_rate,
        bytes_window=bytes_window,
        daily=list(daily.values()),
        verification=verification,
        disk_total_bytes=disk.total,
        disk_used_bytes=disk.used,
        disk_free_bytes=disk.free,
        backups_bytes=backups_bytes,
        storage_history=list(by_day.values()),
        top_clients=[ClientSize(id=c.id, name=c.name, slug=c.slug, stored_bytes=c.stored_bytes)
                     for c in top if c.stored_bytes > 0],
        recent_problems=[
            RecentProblem(
                id=b.id, client_name=b.client.name, received_at=b.received_at,
                status=b.status.value, verify_status=b.verify_status.value,
                message=(b.verify_message if b.verify_status == VerifyStatus.failed else b.error_message),
            )
            for b in problems
        ],
        overdue_clients=overdue,
        worker=WorkerInfo(online=online, last_seen_at=ws.last_seen_at if ws else None,
                          deep_verify=bool(ws and ws.deep_verify), message=ws.message if ws else None,
                          busy_with=ws.busy_with if ws else None, busy_since=ws.busy_since if ws else None),
    )
