"""Cifragem simétrica de segredos em repouso (mfa_secret)."""

from cryptography.fernet import Fernet

from app.core.config import settings

_fernet = Fernet(settings.fernet_key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()
