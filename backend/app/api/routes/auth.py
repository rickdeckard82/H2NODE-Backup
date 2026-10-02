from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, enforce_csrf, get_current_user
from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.db import get_db
from app.core.ratelimit import limiter
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    create_mfa_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    new_csrf_token,
    utcnow,
    verify_password,
)
from app.models import RefreshToken, SystemUser
from app.schemas.auth import (
    ChangePasswordIn,
    LoginIn,
    MeOut,
    MeUpdateIn,
    MfaCodeIn,
    MfaDisableIn,
    MfaEnableOut,
    MfaRegenerateIn,
    MfaSetupOut,
    MfaVerifyIn,
    RecoveryCodesOut,
    SessionOut,
)
from app.schemas.common import Message
from app.services import audit, twofactor

router = APIRouter(prefix="/auth", tags=["auth"])

_MAX_FAILED_LOGINS = 5
# Backoff exponencial: 15min, 30min, 60min, 2h, 4h... até o teto de 24h.
_LOCKOUT_BASE_MINUTES = 15
_LOCKOUT_CAP_MINUTES = 24 * 60
_TOKEN_GC_KEEP_DAYS = 1  # remove tokens expirados/revogados há mais de 1 dia


def _lockout_minutes(strikes: int) -> int:
    return min(_LOCKOUT_BASE_MINUTES * (2 ** max(strikes - 1, 0)), _LOCKOUT_CAP_MINUTES)


def _mfa_code_ok(user: SystemUser, code: str) -> bool:
    """Aceita um TOTP válido OU consome (uso único) um código de recuperação."""
    if user.mfa_secret and twofactor.verify_code(decrypt(user.mfa_secret), code):
        return True
    return twofactor.consume_recovery_code(user, code)


def _gc_refresh_tokens(db: Session) -> None:
    """Poda oportunista: limpa refresh tokens já expirados/revogados e antigos."""
    cutoff = utcnow() - timedelta(days=_TOKEN_GC_KEEP_DAYS)
    db.execute(
        delete(RefreshToken)
        .where(
            or_(RefreshToken.expires_at < cutoff, RefreshToken.revoked.is_(True)),
            RefreshToken.issued_at < cutoff,
        )
        .execution_options(synchronize_session=False)
    )


def _set_auth_cookies(resp: Response, *, access: str, refresh: str, csrf: str) -> None:
    common = {
        "secure": settings.cookie_secure,
        "samesite": "strict",
        "domain": settings.cookie_domain,
    }
    resp.set_cookie(
        settings.access_cookie_name, access, httponly=True, path="/",
        max_age=settings.access_token_ttl_minutes * 60, **common,
    )
    resp.set_cookie(
        settings.refresh_cookie_name, refresh, httponly=True, path="/api/auth",
        max_age=settings.refresh_token_ttl_days * 86400, **common,
    )
    # CSRF: legível pelo JS (double-submit), portanto httponly=False
    resp.set_cookie(
        settings.csrf_cookie_name, csrf, httponly=False, path="/",
        max_age=settings.refresh_token_ttl_days * 86400, **common,
    )


def _clear_auth_cookies(resp: Response) -> None:
    for name, path in (
        (settings.access_cookie_name, "/"),
        (settings.refresh_cookie_name, "/api/auth"),
        (settings.csrf_cookie_name, "/"),
    ):
        resp.delete_cookie(name, path=path, domain=settings.cookie_domain)


def _issue_session(db: Session, resp: Response, user: SystemUser, request: Request) -> str:
    access = create_access_token(str(user.id), user.role.value)
    refresh, jti, exp = create_refresh_token(str(user.id))
    csrf = new_csrf_token()
    db.add(
        RefreshToken(
            jti=jti, system_user_id=user.id, expires_at=exp,
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
            ip_address=client_ip(request),
        )
    )
    _set_auth_cookies(resp, access=access, refresh=refresh, csrf=csrf)
    return csrf


def _complete_login(
    db: Session, response: Response, user: SystemUser, request: Request
) -> SessionOut:
    """Fecha o login (sem 2FA pendente): reseta contadores, abre sessão, audita."""
    user.failed_login_count = 0
    user.lockout_strikes = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    _gc_refresh_tokens(db)
    csrf = _issue_session(db, response, user, request)
    audit.record(
        db, action="login", entity_type="system_user", entity_id=user.id,
        actor_id=user.id, actor_username=user.username, ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return SessionOut(user=MeOut.model_validate(user), csrf_token=csrf)


@router.post("/login", response_model=SessionOut)
@limiter.limit("10/minute")
def login(
    body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> SessionOut:
    user = db.execute(
        select(SystemUser).where(SystemUser.username == body.username)
    ).scalar_one_or_none()

    # Conta bloqueada por tentativas malsucedidas.
    if user is not None and user.locked_until and user.locked_until > utcnow():
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "conta temporariamente bloqueada por excesso de tentativas; tente mais tarde",
        )

    # verify_password sempre executa (mesmo com usuário inexistente, contra um
    # hash descartável) para não vazar a existência da conta por timing.
    password_ok = verify_password(
        body.password, user.password_hash if user else DUMMY_PASSWORD_HASH
    )

    if user is None or not password_ok:
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= _MAX_FAILED_LOGINS:
                user.lockout_strikes += 1
                user.locked_until = utcnow() + timedelta(
                    minutes=_lockout_minutes(user.lockout_strikes)
                )
                user.failed_login_count = 0
                audit.record(
                    db, action="lockout", entity_type="system_user", entity_id=user.id,
                    actor_username=user.username, ip_address=client_ip(request),
                    after={"locked_until": user.locked_until},
                )
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "credenciais inválidas")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "conta desativada")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    if user.mfa_enabled:
        db.commit()  # persiste o rehash de senha, se houve, antes de sair sem sessão
        return SessionOut(mfa_required=True, mfa_token=create_mfa_token(str(user.id)))

    return _complete_login(db, response, user, request)


@router.post("/mfa/verify", response_model=SessionOut)
@limiter.limit("10/minute")
def verify_mfa(
    body: MfaVerifyIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> SessionOut:
    try:
        payload = decode_token(body.mfa_token, expected_type="mfa")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão de 2FA expirada") from exc

    user = db.get(SystemUser, int(payload["sub"]))
    if user is None or not user.is_active or not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão de 2FA inválida")
    if not _mfa_code_ok(user, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "código de 2FA inválido")
    return _complete_login(db, response, user, request)


@router.post("/refresh", response_model=SessionOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> SessionOut:
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sem refresh token")
    try:
        payload = decode_token(token, expected_type="refresh")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh inválido") from exc

    stored = db.execute(
        select(RefreshToken).where(RefreshToken.jti == payload["jti"])
    ).scalar_one_or_none()
    if stored is None or stored.revoked or stored.expires_at < utcnow():
        # reuso de token revogado => derruba toda a árvore de sessões do usuário
        if stored is not None:
            db.query(RefreshToken).filter(
                RefreshToken.system_user_id == stored.system_user_id,
                RefreshToken.revoked.is_(False),
            ).update({"revoked": True})
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh revogado")

    user = db.get(SystemUser, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "conta inativa")

    stored.revoked = True
    csrf = _issue_session(db, response, user, request)
    db.commit()
    return SessionOut(user=MeOut.model_validate(user), csrf_token=csrf)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(settings.refresh_cookie_name)
    if token:
        try:
            payload = decode_token(token, expected_type="refresh")
            db.query(RefreshToken).filter(RefreshToken.jti == payload["jti"]).update(
                {"revoked": True}
            )
            db.commit()
        except jwt.InvalidTokenError:
            pass
    _clear_auth_cookies(response)
    return {"detail": "sessão encerrada"}


@router.get("/me", response_model=MeOut)
def me(user: SystemUser = Depends(get_current_user)) -> MeOut:
    return MeOut.model_validate(user)


@router.patch("/me", response_model=MeOut, dependencies=[Depends(enforce_csrf)])
def update_me(
    body: MeUpdateIn,
    db: Session = Depends(get_db), user: SystemUser = Depends(get_current_user),
) -> MeOut:
    """Preferências do próprio usuário — fuso horário."""
    if body.timezone is not None:
        try:
            ZoneInfo(body.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "fuso horário inválido"
            ) from exc
        user.timezone = body.timezone
    db.commit()
    db.refresh(user)
    return MeOut.model_validate(user)


@router.patch("/me/password", response_model=Message, dependencies=[Depends(enforce_csrf)])
@limiter.limit("10/minute")
def change_my_password(
    body: ChangePasswordIn, request: Request,
    db: Session = Depends(get_db), user: SystemUser = Depends(get_current_user),
) -> Message:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "senha atual incorreta")
    user.password_hash = hash_password(body.new_password)
    audit.record(
        db, action="change_password", entity_type="system_user", entity_id=user.id,
        actor_id=user.id, actor_username=user.username, ip_address=client_ip(request),
    )
    db.commit()
    return Message(detail="senha alterada com sucesso")


@router.post("/mfa/setup", response_model=MfaSetupOut, dependencies=[Depends(enforce_csrf)])
def setup_mfa(
    db: Session = Depends(get_db), user: SystemUser = Depends(get_current_user)
) -> MfaSetupOut:
    if user.mfa_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "2FA já está ativo — desative antes de reconfigurar")
    secret = twofactor.generate_secret()
    user.mfa_secret = encrypt(secret)  # pendente até /mfa/enable confirmar o código
    db.commit()
    uri = twofactor.provisioning_uri(secret, username=user.username)
    return MfaSetupOut(secret=secret, otpauth_uri=uri, qr_svg=twofactor.qr_data_uri(uri))


@router.post("/mfa/enable", response_model=MfaEnableOut, dependencies=[Depends(enforce_csrf)])
def enable_mfa(
    body: MfaCodeIn, request: Request,
    db: Session = Depends(get_db), user: SystemUser = Depends(get_current_user),
) -> MfaEnableOut:
    if user.mfa_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "2FA já está ativo")
    if not user.mfa_secret:
        raise HTTPException(status.HTTP_409_CONFLICT, "inicie o setup em /auth/mfa/setup primeiro")
    if not twofactor.verify_code(decrypt(user.mfa_secret), body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "código de 2FA inválido")
    user.mfa_enabled = True
    codes = twofactor.issue_recovery_codes(user)
    audit.record(db, action="enable_mfa", entity_type="system_user", entity_id=user.id,
                 actor_id=user.id, actor_username=user.username, ip_address=client_ip(request))
    db.commit()
    return MfaEnableOut(detail="2FA ativado", recovery_codes=codes)


@router.post("/mfa/disable", response_model=Message, dependencies=[Depends(enforce_csrf)])
def disable_mfa(
    body: MfaDisableIn, request: Request,
    db: Session = Depends(get_db), user: SystemUser = Depends(get_current_user),
) -> Message:
    if not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status.HTTP_409_CONFLICT, "2FA não está ativo")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "senha incorreta")
    if not _mfa_code_ok(user, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "código de 2FA inválido")
    user.mfa_enabled = False
    user.mfa_secret = None
    twofactor.discard_recovery_codes(user)
    audit.record(db, action="disable_mfa", entity_type="system_user", entity_id=user.id,
                 actor_id=user.id, actor_username=user.username, ip_address=client_ip(request))
    db.commit()
    return Message(detail="2FA desativado")


@router.post(
    "/mfa/recovery-codes/regenerate",
    response_model=RecoveryCodesOut,
    dependencies=[Depends(enforce_csrf)],
)
def regenerate_recovery_codes(
    body: MfaRegenerateIn, request: Request,
    db: Session = Depends(get_db), user: SystemUser = Depends(get_current_user),
) -> RecoveryCodesOut:
    """Gera um lote novo de códigos de recuperação e invalida os anteriores."""
    if not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status.HTTP_409_CONFLICT, "2FA não está ativo")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "senha incorreta")
    if not _mfa_code_ok(user, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "código de 2FA inválido")
    codes = twofactor.issue_recovery_codes(user)
    audit.record(db, action="regenerate_mfa_recovery_codes", entity_type="system_user",
                 entity_id=user.id, actor_id=user.id, actor_username=user.username,
                 ip_address=client_ip(request))
    db.commit()
    return RecoveryCodesOut(recovery_codes=codes)
