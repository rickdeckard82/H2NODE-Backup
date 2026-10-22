from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, enforce_csrf, require_admin
from app.core.db import get_db
from app.core.security import hash_password
from app.models import FirmwareSettings, FtpAccount, SystemUser
from app.schemas.ftp_account import FtpAccountCreate, FtpAccountOut, FtpAccountUpdate
from app.services import audit, receivers

router = APIRouter(
    prefix="/ftp-accounts", tags=["ftp-accounts"],
    dependencies=[Depends(enforce_csrf), Depends(require_admin)],
)


@router.get("", response_model=list[FtpAccountOut])
def list_accounts(db: Session = Depends(get_db)) -> list[FtpAccountOut]:
    rows = db.execute(select(FtpAccount).order_by(FtpAccount.username)).scalars()
    return [FtpAccountOut.model_validate(a) for a in rows]


@router.post("", response_model=FtpAccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    body: FtpAccountCreate, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> FtpAccountOut:
    if db.execute(select(FtpAccount.id).where(FtpAccount.username == body.username)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "já existe uma conta com este usuário")
    fw = db.get(FirmwareSettings, 1)
    if fw and fw.ftp_username == body.username:
        raise HTTPException(status.HTTP_409_CONFLICT, "este usuário é o login do servidor de firmwares")
    a = FtpAccount(username=body.username, password_hash=hash_password(body.password),
                   description=body.description, is_active=body.is_active)
    db.add(a)
    db.flush()
    audit.record(db, action="create", entity_type="ftp_account", entity_id=a.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 after={"username": a.username})
    db.commit()
    receivers.sync(db)
    return FtpAccountOut.model_validate(a)


@router.patch("/{account_id}", response_model=FtpAccountOut)
def update_account(
    account_id: int, body: FtpAccountUpdate, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> FtpAccountOut:
    a = db.get(FtpAccount, account_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    if body.password:
        a.password_hash = hash_password(body.password)
    if body.description is not None:
        a.description = body.description
    if body.is_active is not None:
        a.is_active = body.is_active
    audit.record(db, action="update", entity_type="ftp_account", entity_id=a.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 after={"username": a.username, "is_active": a.is_active,
                        "password_changed": bool(body.password)})
    db.commit()
    receivers.sync(db)
    return FtpAccountOut.model_validate(a)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: int, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> None:
    a = db.get(FtpAccount, account_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    db.delete(a)
    audit.record(db, action="delete", entity_type="ftp_account", entity_id=account_id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 before={"username": a.username})
    db.commit()
    receivers.sync(db)
