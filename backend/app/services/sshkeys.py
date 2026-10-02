"""Chaves SSH dos agentes e o authorized_keys do container sshd.

Cada cliente ativo com chave vira UMA linha:

    restrict,command="/usr/bin/rrsync -wo -no-del /data/incoming/<slug>" ssh-ed25519 AAAA… pulse-backup:<slug>

- `restrict`: sem pty, sem port/agent/X11 forwarding.
- `rrsync -wo -no-del`: o agente só consegue ESCREVER dentro da própria pasta
  de upload — não lista, não lê, não apaga nada (nem o que já enviou).
"""

import base64
import hashlib
import os
import re
import struct
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.models import Client

_ALLOWED_TYPES = {
    "ssh-ed25519",
    "ssh-rsa",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
}
_MIN_RSA_BITS = 3072
_KEY_RE = re.compile(r"^(?P<type>[a-z0-9-]+)\s+(?P<b64>[A-Za-z0-9+/]+={0,3})(?:\s+.*)?$")

AUTHORIZED_KEYS = "authorized_keys"
HOST_KEY_PUB = "ssh_host_ed25519_key.pub"


class InvalidSshKey(ValueError):
    pass


def _read_string(blob: bytes, off: int) -> tuple[bytes, int]:
    if off + 4 > len(blob):
        raise InvalidSshKey("chave SSH truncada")
    (n,) = struct.unpack(">I", blob[off:off + 4])
    off += 4
    if off + n > len(blob):
        raise InvalidSshKey("chave SSH truncada")
    return blob[off:off + n], off + n


def parse_public_key(text: str) -> tuple[str, str]:
    """Valida uma chave pública OpenSSH e devolve (linha normalizada sem
    comentário, fingerprint SHA256:…). Rejeita opções no início da linha."""
    line = " ".join(text.strip().split())
    if "\n" in text.strip():
        raise InvalidSshKey("informe uma única chave (uma linha)")
    m = _KEY_RE.match(line)
    if not m:
        raise InvalidSshKey("formato inválido — cole o conteúdo de id_ed25519.pub")
    ktype, b64 = m.group("type"), m.group("b64")
    if ktype not in _ALLOWED_TYPES:
        raise InvalidSshKey(f"tipo de chave não aceito: {ktype} (use ed25519)")
    try:
        blob = base64.b64decode(b64, validate=True)
    except ValueError as exc:
        raise InvalidSshKey("base64 inválido na chave") from exc
    inner, off = _read_string(blob, 0)
    if inner.decode(errors="replace") != ktype:
        raise InvalidSshKey("tipo declarado não confere com o conteúdo da chave")
    if ktype == "ssh-rsa":
        _e, off = _read_string(blob, off)
        n, off = _read_string(blob, off)
        bits = int.from_bytes(n, "big").bit_length()
        if bits < _MIN_RSA_BITS:
            raise InvalidSshKey(f"chave RSA muito curta ({bits} bits) — use ed25519 ou RSA ≥ {_MIN_RSA_BITS}")
    fp = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return f"{ktype} {b64}", f"SHA256:{fp}"


def _shared_dir() -> Path:
    return Path(settings.ssh_shared_dir)


def _incoming_dir(slug: str) -> str:
    return f"{settings.storage_path.rstrip('/')}/incoming/{slug}"


def render_authorized_keys(clients: list[Client]) -> str:
    lines = [
        "# Gerado pelo Pulse Backup — NÃO edite à mão (é reescrito a cada alteração de cliente).",
    ]
    for c in sorted(clients, key=lambda x: x.slug):
        if not c.is_active or not c.ssh_public_key:
            continue
        cmd = f"/usr/bin/rrsync -wo -no-del {_incoming_dir(c.slug)}"
        lines.append(f'restrict,command="{cmd}" {c.ssh_public_key} pulse-backup:{c.slug}')
    return "\n".join(lines) + "\n"


def sync_authorized_keys(db: Session) -> bool:
    """Reescreve o authorized_keys de forma atômica. Devolve False se o volume
    compartilhado não existir (dev/testes sem o container sshd)."""
    d = _shared_dir()
    if not d.is_dir():
        logger.warning("ssh_shared_dir_missing", path=str(d))
        return False
    clients = list(db.execute(select(Client)).scalars())
    content = render_authorized_keys(clients)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".authorized_keys.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        # sshd (StrictModes) recusa arquivo gravável por grupo/outros.
        os.chmod(tmp, 0o644)
        os.replace(tmp, d / AUTHORIZED_KEYS)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def host_key() -> tuple[str | None, str | None]:
    """(linha da chave pública de host do sshd, fingerprint SHA256)."""
    p = _shared_dir() / HOST_KEY_PUB
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None, None
    try:
        line, fp = parse_public_key(text)
    except InvalidSshKey:
        return None, None
    return line, fp


def known_hosts_line(host_line: str) -> str:
    host = settings.ssh_public_host
    port = settings.ssh_public_port
    target = host if port == 22 else f"[{host}]:{port}"
    return f"{target} {host_line}"
