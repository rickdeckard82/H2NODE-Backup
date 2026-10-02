"""2FA para usuários do painel: TOTP (RFC 6238) + códigos de recuperação."""

import secrets

import pyotp
import segno

from app.core.security import hash_password, utcnow, verify_password
from app.models import MfaRecoveryCode, SystemUser

_ISSUER = "Pulse Backup"

# Códigos de recuperação: uso único, mostrados só na ativação. Alfabeto sem
# caracteres ambíguos (0/O, 1/I/L). 10 grupos de 5 => ~51 bits de entropia.
_RECOVERY_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_RECOVERY_COUNT = 10
_RECOVERY_LEN = 10  # dígitos antes de formatar como XXXXX-XXXXX


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, username: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=_ISSUER)


def qr_data_uri(otpauth_uri: str) -> str:
    """QR code do otpauth:// como data URI (SVG), para escanear no cadastro do 2FA."""
    return segno.make(otpauth_uri, error="m").svg_data_uri(scale=4, border=2)


def verify_code(secret: str, code: str) -> bool:
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    # valid_window=1 tolera deriva de ±30s entre o relógio do servidor e do app.
    return pyotp.totp.TOTP(secret).verify(code, valid_window=1)


def _new_recovery_code() -> str:
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_LEN))
    return f"{raw[:5]}-{raw[5:]}"


def _normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.strip().upper() if ch in _RECOVERY_ALPHABET)


def issue_recovery_codes(user: SystemUser) -> list[str]:
    """Descarta os códigos anteriores do usuário e gera um lote novo.

    Retorna os códigos em claro (para exibir uma única vez); no banco fica só o
    hash. Mexe na coleção ORM — quem chama faz o commit.
    """
    user.mfa_recovery_codes.clear()  # delete-orphan remove os antigos no flush
    codes = [_new_recovery_code() for _ in range(_RECOVERY_COUNT)]
    for c in codes:
        user.mfa_recovery_codes.append(
            MfaRecoveryCode(code_hash=hash_password(_normalize_recovery_code(c)))
        )
    return codes


def discard_recovery_codes(user: SystemUser) -> None:
    user.mfa_recovery_codes.clear()


def consume_recovery_code(user: SystemUser, code: str) -> bool:
    """Confere `code` contra os códigos de recuperação não usados do usuário.

    Se coincidir, marca-o como usado (sem commit) e devolve True.
    """
    candidate = _normalize_recovery_code(code)
    if len(candidate) != _RECOVERY_LEN:
        return False
    for row in user.mfa_recovery_codes:
        if row.used_at is None and verify_password(candidate, row.code_hash):
            row.used_at = utcnow()
            return True
    return False
