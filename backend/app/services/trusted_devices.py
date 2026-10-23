"""Dispositivos lembrados no 2FA (TRUSTED_DEVICE_DAYS, padrão 30; 0 desliga).

O cookie (HttpOnly, SameSite=Strict, só em /api/auth) carrega um token aleatório; o banco
guarda o SHA-256. Vale só para o usuário que o criou e só dispensa o código 2FA — a senha
continua sendo pedida. Revogado ao trocar a senha, desativar/redefinir o 2FA, desativar a
conta ou por "esquecer dispositivos".
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import utcnow
from app.models import TrustedDevice

COOKIE = "pb_trusted"
COOKIE_PATH = "/api/auth"


def enabled() -> bool:
    return settings.trusted_device_days > 0


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(db: Session, user_id: int, *, user_agent: str | None, ip: str | None) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    # poda os vencidos deste usuário a cada novo dispositivo
    db.execute(delete(TrustedDevice).where(TrustedDevice.system_user_id == user_id,
                                           TrustedDevice.expires_at < now))
    db.add(TrustedDevice(system_user_id=user_id, token_hash=_hash(token),
                         expires_at=now + timedelta(days=settings.trusted_device_days),
                         user_agent=(user_agent or "")[:255] or None, ip_address=ip))
    return token


def check(db: Session, user_id: int, token: str | None) -> bool:
    """Token válido e deste usuário? Marca o uso."""
    if not enabled() or not token or len(token) > 128:
        return False
    row = db.execute(
        select(TrustedDevice).where(TrustedDevice.token_hash == _hash(token))
    ).scalar_one_or_none()
    if row is None or row.system_user_id != user_id or row.expires_at < utcnow():
        return False
    row.last_used_at = utcnow()
    return True


def revoke_all(db: Session, user_id: int) -> int:
    res = db.execute(delete(TrustedDevice).where(TrustedDevice.system_user_id == user_id))
    return res.rowcount or 0


def count(db: Session, user_id: int) -> int:
    return len(db.execute(select(TrustedDevice.id).where(TrustedDevice.system_user_id == user_id,
                                                         TrustedDevice.expires_at >= utcnow())).all())
