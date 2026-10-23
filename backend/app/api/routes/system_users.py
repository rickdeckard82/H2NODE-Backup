from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, enforce_csrf, require_admin
from app.core.db import get_db
from app.core.security import hash_password
from app.models import RefreshToken, SystemRole, SystemUser
from app.schemas.common import Message, Page
from app.schemas.system_user import SystemUserCreate, SystemUserOut, SystemUserUpdate
from app.services import audit, trusted_devices, twofactor

router = APIRouter(
    prefix="/system-users",
    tags=["system-users"],
    dependencies=[Depends(enforce_csrf)],
)


def _check_tz(tz: str) -> None:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "fuso horário inválido") from exc


def _count_active_admins(db: Session, exclude_id: int | None = None) -> int:
    q = select(func.count()).select_from(SystemUser).where(
        SystemUser.role == SystemRole.admin, SystemUser.is_active.is_(True)
    )
    if exclude_id is not None:
        q = q.where(SystemUser.id != exclude_id)
    return db.execute(q).scalar_one()


def _revoke_sessions(db: Session, user_id: int) -> None:
    db.query(RefreshToken).filter(
        RefreshToken.system_user_id == user_id, RefreshToken.revoked.is_(False)
    ).update({"revoked": True})
    # senha redefinida / conta desativada: navegadores lembrados no 2FA também caem
    trusted_devices.revoke_all(db, user_id)


@router.get("", response_model=Page[SystemUserOut])
def list_users(
    db: Session = Depends(get_db),
    _: SystemUser = Depends(require_admin),
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> Page[SystemUserOut]:
    stmt = select(SystemUser)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(SystemUser.username.ilike(like), SystemUser.email.ilike(like),
                              SystemUser.full_name.ilike(like)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(SystemUser.username).limit(page_size).offset((page - 1) * page_size)
    ).scalars()
    return Page(items=[SystemUserOut.model_validate(r) for r in rows],
                total=total, page=page, page_size=page_size)


@router.post("", response_model=SystemUserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: SystemUserCreate, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> SystemUserOut:
    _check_tz(body.timezone)
    if db.execute(select(SystemUser).where(
        or_(SystemUser.username == body.username, SystemUser.email == body.email)
    )).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "username ou e-mail já em uso")
    user = SystemUser(
        username=body.username, email=body.email, full_name=body.full_name,
        role=body.role, is_active=body.is_active, timezone=body.timezone,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.flush()
    audit.record(db, action="create", entity_type="system_user", entity_id=user.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 after={"username": user.username, "role": user.role.value})
    db.commit()
    return SystemUserOut.model_validate(user)


@router.patch("/{user_id}", response_model=SystemUserOut)
def update_user(
    user_id: int, body: SystemUserUpdate, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> SystemUserOut:
    user = db.get(SystemUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")

    before = {"role": user.role.value, "is_active": user.is_active, "email": user.email}
    demoting = (body.role is not None and body.role != SystemRole.admin) or body.is_active is False
    if user.role == SystemRole.admin and demoting and _count_active_admins(db, user.id) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "não pode remover o último admin ativo")
    if body.email is not None and body.email != user.email and db.execute(
        select(SystemUser.id).where(SystemUser.email == body.email)
    ).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "e-mail já em uso")

    if body.email is not None:
        user.email = body.email
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
        if not body.is_active:
            _revoke_sessions(db, user.id)
    if body.timezone is not None:
        _check_tz(body.timezone)
        user.timezone = body.timezone
    if body.password:
        user.password_hash = hash_password(body.password)
        _revoke_sessions(db, user.id)

    audit.record(db, action="update", entity_type="system_user", entity_id=user.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 before=before,
                 after={"role": user.role.value, "is_active": user.is_active, "email": user.email,
                        "password_changed": bool(body.password)})
    db.commit()
    return SystemUserOut.model_validate(user)


@router.post("/{user_id}/reset-mfa", response_model=Message)
def reset_mfa(
    user_id: int, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> Message:
    """Recovery: desativa o 2FA de outro usuário (perda do dispositivo TOTP)."""
    user = db.get(SystemUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    if not user.mfa_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "2FA não está ativo para este usuário")
    user.mfa_enabled = False
    user.mfa_secret = None
    trusted_devices.revoke_all(db, user.id)
    twofactor.discard_recovery_codes(user)
    audit.record(db, action="reset_mfa", entity_type="system_user", entity_id=user.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request))
    db.commit()
    return Message(detail=f"2FA de {user.username} foi desativado")


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> None:
    if user_id == actor.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "não pode excluir a própria conta")
    user = db.get(SystemUser, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    if user.role == SystemRole.admin and _count_active_admins(db, user.id) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "não pode excluir o último admin ativo")
    db.delete(user)
    audit.record(db, action="delete", entity_type="system_user", entity_id=user_id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 before={"username": user.username, "role": user.role.value})
    db.commit()
