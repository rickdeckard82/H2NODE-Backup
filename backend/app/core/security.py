"""Hash de senha (Argon2id) e emissão/validação de JWT para usuários do painel."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from app.core.config import settings

_ph = PasswordHasher()

# Hash real e descartável para igualar o tempo de verificação quando a conta não
# existe (mitiga enumeração de usuários por timing). Calculado uma vez.
DUMMY_PASSWORD_HASH = _ph.hash("h2node-backup-timing-equalizer")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except (Argon2Error, ValueError):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _ph.check_needs_rehash(hashed)
    except (Argon2Error, ValueError):
        return False


def utcnow() -> datetime:
    """UTC sem tzinfo — colunas TIMESTAMP sem fuso guardam sempre UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def create_access_token(sub: str, role: str) -> str:
    now = utcnow()
    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(sub: str) -> tuple[str, str, datetime]:
    """Retorna (token, jti, expiração naive-UTC)."""
    now = utcnow()
    jti = uuid.uuid4().hex
    exp = now + timedelta(days=settings.refresh_token_ttl_days)
    payload: dict[str, Any] = {
        "sub": sub,
        "type": "refresh",
        "iat": now,
        "exp": exp,
        "jti": jti,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti, exp


_MFA_TOKEN_TTL_MINUTES = 5


def create_mfa_token(sub: str) -> str:
    """Token curto emitido após validar usuário+senha quando o 2FA está ativo —
    prova que a 1ª etapa passou, sem ainda abrir sessão (ver /auth/mfa/verify)."""
    now = utcnow()
    payload: dict[str, Any] = {
        "sub": sub,
        "type": "mfa",
        "iat": now,
        "exp": now + timedelta(minutes=_MFA_TOKEN_TTL_MINUTES),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("tipo de token inesperado")
    return payload


def new_csrf_token() -> str:
    return uuid.uuid4().hex
