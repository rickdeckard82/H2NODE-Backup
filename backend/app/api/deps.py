from collections.abc import Iterable

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import decode_token
from app.models import SystemRole, SystemUser

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_current_user(request: Request, db: Session = Depends(get_db)) -> SystemUser:
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "não autenticado")
    try:
        payload = decode_token(token, expected_type="access")
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão expirada") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido") from exc

    user = db.get(SystemUser, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "conta inativa")
    return user


def enforce_csrf(request: Request) -> None:
    """Double-submit cookie: header X-CSRF-Token deve coincidir com o cookie."""
    if request.method not in _UNSAFE_METHODS:
        return
    cookie = request.cookies.get(settings.csrf_cookie_name)
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or cookie != header:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token ausente ou inválido")


def require_roles(*roles: SystemRole):
    allowed: Iterable[SystemRole] = roles

    def _dep(user: SystemUser = Depends(get_current_user)) -> SystemUser:
        if user.role == SystemRole.admin:
            return user
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "permissão insuficiente")
        return user

    return _dep


# Atalhos
require_auditor = require_roles(SystemRole.auditor, SystemRole.operator)
require_operator = require_roles(SystemRole.operator)
require_admin = require_roles()  # só admin (lista vazia => cai no check acima)


def client_ip(request: Request) -> str | None:
    """IP do cliente para auditoria/registro.

    Só é confiável se o reverse proxy da borda SUBSTITUIR o X-Forwarded-For pelo
    IP real (ex.: no Nginx Proxy Manager: `proxy_set_header X-Forwarded-For
    $remote_addr;`). Caso contrário o primeiro valor é fornecido pelo cliente e
    pode ser forjado. Ver docs/deploy.md.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
