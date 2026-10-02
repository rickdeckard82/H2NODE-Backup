from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, enforce_csrf, require_admin, require_auditor, require_operator
from app.core.db import get_db
from app.models import Backup, BackupComponent, BackupStatus, Client, SystemUser, VerifyStatus
from app.schemas.backup import BackupDetailOut, BackupOut
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
    status_: BackupStatus | None = Query(None, alias="status"),
    verify_status: VerifyStatus | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    include_deleted: bool = False,
    problems: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> Page[BackupOut]:
    stmt = select(Backup)
    if client_id:
        stmt = stmt.where(Backup.client_id == client_id)
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
