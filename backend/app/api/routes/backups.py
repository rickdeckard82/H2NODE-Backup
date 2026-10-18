from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, enforce_csrf, require_admin, require_auditor, require_operator
from app.core.db import get_db
from app.models import Backup, BackupComponent, BackupStatus, Client, SystemUser, VerifyStatus
from app.schemas.backup import AccountOut, AccountVersionOut, BackupDetailOut, BackupOut
from app.schemas.common import Message, Page
from app.services import audit, storage
from app.services.ingest import refresh_client_stats
from app.services.retention import delete_backup_files

router = APIRouter(prefix="/backups", tags=["backups"], dependencies=[Depends(enforce_csrf)])


def _to_out(b: Backup) -> BackupOut:
    return BackupOut(
        id=b.id, client_id=b.client_id, client_slug=b.client.slug, client_name=b.client.name,
        run_name=b.run_name, status=b.status, agent_status=b.agent_status,
        started_at=b.started_at, finished_at=b.finished_at, received_at=b.received_at,
        size_bytes=b.size_bytes, plain_size_bytes=b.plain_size_bytes,
        error_message=b.error_message, agent_version=b.agent_version,
        verify_status=b.verify_status, verify_mode=b.verify_mode, verified_at=b.verified_at,
        verify_message=b.verify_message, deleted_at=b.deleted_at,
        component_count=len(b.components),
    )


def _get(db: Session, backup_id: int) -> Backup:
    b = db.get(Backup, backup_id)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    return b


@router.get("", response_model=Page[BackupOut])
def list_backups(
    db: Session = Depends(get_db),
    _: SystemUser = Depends(require_auditor),
    client_id: int | None = None,
    # só os backups de equipamentos deste fabricante (ex.: mikrotik)
    vendor: str | None = Query(None, max_length=16),
    status_: BackupStatus | None = Query(None, alias="status"),
    verify_status: VerifyStatus | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    include_deleted: bool = False,
    problems: bool = False,
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> Page[BackupOut]:
    stmt = select(Backup)
    if q:
        # busca pelo nome de uma parte (conta, pasta, banco): só os backups que a contêm
        like = f"%{q.strip()}%"
        stmt = stmt.where(Backup.id.in_(
            select(BackupComponent.backup_id).where(BackupComponent.name.ilike(like))
        ))
    if client_id:
        stmt = stmt.where(Backup.client_id == client_id)
    if vendor:
        stmt = stmt.where(Backup.client_id.in_(select(Client.id).where(Client.vendor == vendor)))
    if status_:
        stmt = stmt.where(Backup.status == status_)
    if verify_status:
        stmt = stmt.where(Backup.verify_status == verify_status)
    if since:
        stmt = stmt.where(Backup.received_at >= since.replace(tzinfo=None))
    if until:
        stmt = stmt.where(Backup.received_at < until.replace(tzinfo=None))
    if problems:
        stmt = stmt.where(or_(Backup.status.in_((BackupStatus.failed, BackupStatus.corrupted)),
                              Backup.verify_status == VerifyStatus.failed))
    if not include_deleted:
        stmt = stmt.where(Backup.deleted_at.is_(None))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(Backup.received_at.desc(), Backup.id.desc())
        .limit(page_size).offset((page - 1) * page_size)
    ).scalars().unique()
    return Page(items=[_to_out(b) for b in rows], total=total, page=page, page_size=page_size)


def _live_files():
    """Componentes "arquivo" (kind=file) de backups que ainda estão guardados."""
    return (
        BackupComponent.kind == "file",
        Backup.deleted_at.is_(None),
        Backup.storage_path.is_not(None),
    )


def _day_bounds(day: date, user: SystemUser) -> tuple[datetime, datetime]:
    """Início e fim (UTC, sem tz — como no banco) do dia no fuso do operador."""
    try:
        tz = ZoneInfo(user.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return (start.astimezone(UTC).replace(tzinfo=None), end.astimezone(UTC).replace(tzinfo=None))


@router.get("/accounts", response_model=Page[AccountOut])
def list_accounts(
    db: Session = Depends(get_db),
    user: SystemUser = Depends(require_auditor),
    q: str | None = Query(None, max_length=100),
    client_id: int | None = None,
    # só as contas com cópia recebida neste dia (no fuso do operador); mostra a cópia desse dia
    day: date | None = None,
    sort: str = Query("name", pattern="^(name|client|received|size|versions|verify)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Page[AccountOut]:
    """Uma linha por conta/arquivo (ex.: cada conta do cPanel) com a cópia mais recente
    (ou a do dia escolhido). "versions" conta sempre todas as cópias guardadas."""
    part = (Backup.client_id, BackupComponent.name)
    if day:
        start, end = _day_bounds(day, user)
        in_day = case((and_(Backup.received_at >= start, Backup.received_at < end), 1), else_=0)
    else:
        # sempre 1; é um CASE porque um literal no ORDER BY vira número de coluna
        in_day = case((Backup.id.is_not(None), 1), else_=0)
    order_by = (in_day.desc(), Backup.received_at.desc(), Backup.id.desc())
    inner = (
        select(
            Backup.client_id.label("client_id"), Client.name.label("client_name"),
            BackupComponent.name.label("name"), BackupComponent.id.label("component_id"),
            BackupComponent.backup_id.label("backup_id"), Backup.received_at.label("received_at"),
            BackupComponent.size_bytes.label("size_bytes"), BackupComponent.status.label("status"),
            BackupComponent.verify_status.label("verify_status"),
            BackupComponent.file_name.label("file_name"),
            in_day.label("in_day"),
            func.row_number().over(partition_by=part, order_by=order_by).label("rn"),
            func.count().over(partition_by=part).label("versions"),
        )
        .join(Backup, Backup.id == BackupComponent.backup_id)
        .join(Client, Client.id == Backup.client_id)
        .where(*_live_files())
    )
    if client_id:
        inner = inner.where(Backup.client_id == client_id)
    if q:
        inner = inner.where(BackupComponent.name.ilike(f"%{q.strip()}%"))
    sub = inner.subquery()
    latest = select(sub).where(sub.c.rn == 1, sub.c.in_day == 1)
    total = db.execute(select(func.count()).select_from(latest.subquery())).scalar_one()
    col = {
        "name": sub.c.name, "client": sub.c.client_name, "received": sub.c.received_at,
        "size": sub.c.size_bytes, "versions": sub.c.versions, "verify": sub.c.verify_status,
    }[sort]
    key = (col.asc() if order == "asc" else col.desc()).nulls_last()
    rows = db.execute(
        latest.order_by(key, sub.c.name, sub.c.client_name).limit(page_size).offset((page - 1) * page_size)
    ).all()
    items = [
        AccountOut(
            client_id=r.client_id, client_name=r.client_name, name=r.name, versions=r.versions,
            last_backup_id=r.backup_id, last_component_id=r.component_id, last_received_at=r.received_at,
            size_bytes=r.size_bytes, status=r.status, verify_status=r.verify_status, file_name=r.file_name,
        )
        for r in rows
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/accounts/history", response_model=list[AccountVersionOut])
def account_history(
    client_id: int, name: str = Query(max_length=255),
    db: Session = Depends(get_db), _: SystemUser = Depends(require_auditor),
) -> list[AccountVersionOut]:
    """Todas as cópias guardadas de uma conta/arquivo, da mais recente para a mais antiga."""
    rows = db.execute(
        select(BackupComponent, Backup)
        .join(Backup, Backup.id == BackupComponent.backup_id)
        .where(*_live_files(), Backup.client_id == client_id, BackupComponent.name == name)
        .order_by(Backup.received_at.desc(), Backup.id.desc())
        .limit(500)
    ).all()
    return [
        AccountVersionOut(
            backup_id=b.id, component_id=c.id, run_name=b.run_name, received_at=b.received_at,
            size_bytes=c.size_bytes, status=c.status, verify_status=c.verify_status,
            verify_message=c.verify_message, file_name=c.file_name,
        )
        for c, b in rows
    ]


@router.get("/{backup_id}", response_model=BackupDetailOut)
def get_backup(
    backup_id: int, db: Session = Depends(get_db), _: SystemUser = Depends(require_auditor)
) -> BackupDetailOut:
    b = _get(db, backup_id)
    base = _to_out(b).model_dump()
    m = b.manifest or {}
    return BackupDetailOut(
        **base,
        components=b.components,  # type: ignore[arg-type]
        errors=[str(e) for e in m.get("errors", [])][:200],
        hostname=m.get("hostname"),
    )


@router.post("/{backup_id}/verify", response_model=Message)
def request_verify(
    backup_id: int, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_operator),
) -> Message:
    b = _get(db, backup_id)
    if b.deleted_at is not None or b.storage_path is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "os arquivos deste backup não estão mais guardados")
    if b.verify_status == VerifyStatus.running:
        raise HTTPException(status.HTTP_409_CONFLICT, "verificação já em andamento")
    b.verify_status = VerifyStatus.pending
    audit.record(db, action="verify", entity_type="backup", entity_id=b.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request))
    db.commit()
    return Message(detail="verificação agendada — o worker processa em instantes")


@router.get("/{backup_id}/components/{component_id}/download")
def download_component(
    backup_id: int, component_id: int, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> FileResponse:
    """Baixa o arquivo AINDA CIFRADO (.gpg). Decifrar exige a chave privada,
    que fica fora do painel — ver docs/restore.md."""
    b = _get(db, backup_id)
    comp = db.get(BackupComponent, component_id)
    if comp is None or comp.backup_id != b.id or not comp.file_name:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "componente não encontrado")
    if b.deleted_at is not None or b.storage_path is None:
        raise HTTPException(status.HTTP_410_GONE, "arquivos removidos pela retenção")
    try:
        path = storage.safe_child(storage.root(), *b.storage_path.split("/"), comp.file_name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "arquivo inválido") from exc
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "arquivo não encontrado no armazenamento")
    audit.record(db, action="download", entity_type="backup", entity_id=b.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 after={"component": comp.name, "file": comp.file_name})
    db.commit()
    return FileResponse(
        path, media_type="application/pgp-encrypted",
        filename=f"{b.client.slug}-{b.run_name}-{comp.file_name}",
    )


@router.delete("/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup(
    backup_id: int, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> None:
    b = _get(db, backup_id)
    if b.deleted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "backup já removido")
    try:
        delete_backup_files(b)
    except (ValueError, OSError) as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"falha ao apagar: {exc}") from exc
    client = db.get(Client, b.client_id)
    if client is not None:
        db.flush()
        refresh_client_stats(db, client)
    audit.record(db, action="delete", entity_type="backup", entity_id=b.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 before={"client": b.client.slug, "run": b.run_name, "size": b.size_bytes})
    db.commit()
