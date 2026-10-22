"""Servidor de firmwares: arquivos que os equipamentos BAIXAM por FTP/TFTP (atualização
de switch, OLT, roteador…).

Layout, dentro de STORAGE_PATH:
    firmware/files/   o que é servido (raiz do login FTP de firmware; RRQ do TFTP)
    firmware/.tmp/    envios do painel em andamento (fora da raiz servida)

Nada aqui é backup: é a única área que os receptores servem para leitura, e só ela. Os
arquivos são enviados pelo administrador no painel (página FTP Firmwares).
"""

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import storage
from app.services.downloads import sha256_file

NAME_RE = storage.SAFE_NAME


def base_dir() -> Path:
    return storage.root() / "firmware"


def files_dir() -> Path:
    return base_dir() / "files"


def tmp_dir() -> Path:
    return base_dir() / ".tmp"


def ensure_layout() -> None:
    for d in (files_dir(), tmp_dir()):
        d.mkdir(parents=True, exist_ok=True)
    # os receptores (outro container, mesmo uid) só precisam ler
    files_dir().chmod(0o755)


@dataclass
class FirmwareFile:
    name: str
    size: int
    sha256: str
    updated_at: datetime


def list_files() -> list[FirmwareFile]:
    d = files_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir(), key=lambda x: x.name.lower()):
        if p.is_symlink() or not p.is_file() or not NAME_RE.match(p.name):
            continue
        st = p.stat()
        out.append(FirmwareFile(p.name, st.st_size, sha256_file(p),
                                datetime.fromtimestamp(st.st_mtime, UTC).replace(tzinfo=None)))
    return out


def resolve(requested: str) -> Path | None:
    """Arquivo pedido por um equipamento (TFTP). O caminho é só rótulo: vale o último
    componente ("/firmware/S5720.cc" -> "S5720.cc"); sem diferença de maiúsculas se não
    houver o nome exato e só um arquivo combinar."""
    name = requested.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not NAME_RE.match(name):
        return None
    d = files_dir()
    p = storage.safe_child(d, name)
    if p.is_file() and not p.is_symlink():
        return p
    try:
        low = name.lower()
        same = [x for x in d.iterdir() if x.name.lower() == low and x.is_file() and not x.is_symlink()]
    except OSError:
        return None
    return same[0] if len(same) == 1 else None


# ------------------------------------------------------------ configuração --


def parse_networks(lines: list[str]) -> list[str]:
    """Normaliza as redes liberadas ("192.0.2.10" -> "192.0.2.10/32"). ValueError com a
    linha inválida."""
    out: list[str] = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        try:
            net = ipaddress.ip_network(s, strict=False)
        except ValueError:
            raise ValueError(f"rede inválida: {s!r} (use IP ou CIDR, ex.: 192.0.2.0/24)") from None
        if net.prefixlen == 0:
            raise ValueError(f"rede ampla demais: {s!r} (não libere a internet inteira)")
        if str(net) not in out:
            out.append(str(net))
    return out


def get_settings(db: Session):  # noqa: ANN201
    from app.models import FirmwareSettings

    row = db.get(FirmwareSettings, 1)
    if row is None:
        row = FirmwareSettings(id=1, enabled=False, allowed_networks="", include_devices=True)
        db.add(row)
        db.flush()
    return row


def networks_of(row) -> list[str]:  # noqa: ANN001
    return [n for n in (row.allowed_networks or "").splitlines() if n.strip()]


def max_bytes() -> int:
    return settings.firmware_max_mb * 1024 * 1024
