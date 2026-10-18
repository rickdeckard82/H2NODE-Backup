from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, enforce_csrf, require_admin, require_operator
from app.core import crypto
from app.core.db import get_db
from app.models import Client, DeviceCredential, SystemUser
from app.schemas.device_credential import DeviceCredentialCreate, DeviceCredentialOut, DeviceCredentialUpdate
from app.services import audit

router = APIRouter(prefix="/device-credentials", tags=["device-credentials"],
                   dependencies=[Depends(enforce_csrf)])


def _to_out(db: Session, c: DeviceCredential) -> DeviceCredentialOut:
    out = DeviceCredentialOut.model_validate(c)
    out.device_count = db.execute(
        select(func.count()).select_from(Client).where(Client.pull_credential_id == c.id)
    ).scalar_one()
    return out


def _check_name(db: Session, name: str, own_id: int = 0) -> None:
    if db.execute(select(DeviceCredential.id).where(DeviceCredential.name == name,
                                                    DeviceCredential.id != own_id)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "já existe uma credencial com este nome")


@router.get("", response_model=list[DeviceCredentialOut])
def list_credentials(
    db: Session = Depends(get_db), _: SystemUser = Depends(require_operator)
) -> list[DeviceCredentialOut]:
    rows = db.execute(select(DeviceCredential).order_by(DeviceCredential.name)).scalars()
    return [_to_out(db, c) for c in rows]


@router.post("", response_model=DeviceCredentialOut, status_code=status.HTTP_201_CREATED)
def create_credential(
    body: DeviceCredentialCreate, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> DeviceCredentialOut:
    _check_name(db, body.name)
    c = DeviceCredential(name=body.name, username=body.username, password_enc=crypto.encrypt(body.password),
                         port=body.port, description=body.description)
    db.add(c)
    db.flush()
    audit.record(db, action="create", entity_type="device_credential", entity_id=c.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 after={"name": c.name, "username": c.username, "port": c.port})
    db.commit()
    return _to_out(db, c)


@router.patch("/{cred_id}", response_model=DeviceCredentialOut)
def update_credential(
    cred_id: int, body: DeviceCredentialUpdate, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> DeviceCredentialOut:
    c = db.get(DeviceCredential, cred_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    before = {"name": c.name, "username": c.username, "port": c.port}
    if body.name is not None:
        _check_name(db, body.name, c.id)
        c.name = body.name
    if body.username is not None:
        c.username = body.username
    if body.port is not None:
        c.port = body.port
    if body.description is not None:
        c.description = body.description or None
    if body.password:
        c.password_enc = crypto.encrypt(body.password)
    audit.record(db, action="update", entity_type="device_credential", entity_id=c.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 before=before, after={"name": c.name, "username": c.username, "port": c.port,
                                       "password_changed": bool(body.password)})
    db.commit()
    return _to_out(db, c)


@router.delete("/{cred_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(
    cred_id: int, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> None:
    c = db.get(DeviceCredential, cred_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    used = _to_out(db, c).device_count
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{used} equipamento(s) usam esta credencial — troque-a neles antes")
    db.delete(c)
    audit.record(db, action="delete", entity_type="device_credential", entity_id=cred_id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 before={"name": c.name, "username": c.username})
    db.commit()
