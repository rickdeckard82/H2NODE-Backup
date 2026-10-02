"""Operações com o GnuPG (binário `gpg` da imagem).

Nunca usamos o keyring do usuário: cada operação roda com um GNUPGHOME
descartável (ou o do worker, criado em tmpfs com a chave privada importada).
"""

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.core.config import settings
from app.core.logging import logger

_GPG = "gpg"
_HEADER_BYTES = 64 * 1024  # os pacotes de chave de sessão ficam no início do arquivo
_KEYID_RE = re.compile(r"keyid ([0-9A-F]{16})")


@dataclass
class PublicKeyInfo:
    fingerprint: str
    uid: str | None
    key_ids: set[str] = field(default_factory=set)  # primária + subchaves (16 hex)
    armored: str = ""


def _run(args: list[str], *, home: str, input_bytes: bytes | None = None,
         timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_GPG, "--homedir", home, "--batch", "--no-tty", *args],
        input=input_bytes, capture_output=True, timeout=timeout, check=False,
    )


def _parse_colons(text: str) -> PublicKeyInfo | None:
    fpr = uid = None
    key_ids: set[str] = set()
    expect_primary_fpr = False
    for line in text.splitlines():
        parts = line.split(":")
        rec = parts[0]
        if rec in ("pub", "sub") and len(parts) > 4:
            key_ids.add(parts[4].upper())
            expect_primary_fpr = rec == "pub"
        elif rec == "fpr" and expect_primary_fpr and len(parts) > 9:
            fpr = parts[9].upper()
            expect_primary_fpr = False
        elif rec == "uid" and uid is None and len(parts) > 9:
            uid = parts[9].replace("\\x3a", ":")
    if not fpr:
        return None
    return PublicKeyInfo(fingerprint=fpr, uid=uid, key_ids=key_ids)


def _read_public_key_info(path: str, _mtime: float) -> PublicKeyInfo | None:
    try:
        armored = Path(path).read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return None
    with tempfile.TemporaryDirectory(prefix="pb-gpg-") as home:
        r = _run(
            ["--with-colons", "--import-options", "show-only", "--import"],
            home=home, input_bytes=armored.encode(),
        )
    info = _parse_colons(r.stdout.decode(errors="replace"))
    if info is None:
        logger.warning("gpg_public_key_unreadable", path=path, stderr=r.stderr.decode()[-300:])
        return None
    info.armored = armored
    return info


_cached = lru_cache(maxsize=4)(_read_public_key_info)


def public_key_info() -> PublicKeyInfo | None:
    """Chave pública dos backups (cacheada até o arquivo mudar)."""
    path = settings.backup_public_key_path
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return None
    return _cached(path, mtime)


def recipient_key_ids(path: Path) -> set[str]:
    """IDs das chaves para as quais o arquivo foi cifrado (sem precisar decifrar)."""
    with open(path, "rb") as f:
        head = f.read(_HEADER_BYTES)
    with tempfile.TemporaryDirectory(prefix="pb-gpg-") as home:
        r = _run(["--list-packets"], home=home, input_bytes=head)
    out = r.stdout.decode(errors="replace") + r.stderr.decode(errors="replace")
    return {m.upper() for m in _KEYID_RE.findall(out)}


class PrivateKeyring:
    """GNUPGHOME com a chave privada importada (só no worker)."""

    def __init__(self) -> None:
        self.home: str | None = None
        self.passphrase_file: str | None = None
        self.error: str | None = None

    @property
    def available(self) -> bool:
        return self.home is not None

    def load(self) -> None:
        path = settings.backup_private_key_path
        if not path:
            self.error = "BACKUP_PRIVATE_KEY_PATH não definido — verificação só de integridade"
            return
        if not Path(path).is_file():
            self.error = f"chave privada não encontrada em {path}"
            return
        home = tempfile.mkdtemp(prefix="pb-gnupg-")
        os.chmod(home, 0o700)
        r = _run(["--import"], home=home, input_bytes=Path(path).read_bytes())
        if r.returncode != 0:
            shutil.rmtree(home, ignore_errors=True)
            self.error = "falha ao importar a chave privada: " + r.stderr.decode(errors="replace")[-300:]
            return
        listing = _run(["--with-colons", "--list-secret-keys"], home=home)
        if "sec:" not in listing.stdout.decode(errors="replace"):
            shutil.rmtree(home, ignore_errors=True)
            self.error = "o arquivo informado não contém uma chave privada"
            return
        if settings.backup_key_passphrase:
            fd, pf = tempfile.mkstemp(dir=home, prefix="pass.")
            with os.fdopen(fd, "w") as f:
                f.write(settings.backup_key_passphrase)
            self.passphrase_file = pf
        self.home = home
        self.error = None

    def decrypt_cmd(self) -> list[str]:
        assert self.home is not None
        cmd = [_GPG, "--homedir", self.home, "--batch", "--no-tty", "--quiet",
               "--pinentry-mode", "loopback"]
        if self.passphrase_file:
            cmd += ["--passphrase-file", self.passphrase_file]
        else:
            cmd += ["--passphrase", ""]
        return cmd + ["--decrypt"]
