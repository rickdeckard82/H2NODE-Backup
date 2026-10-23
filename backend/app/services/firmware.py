"""Servidor de firmwares: arquivos que os equipamentos BAIXAM por FTP/TFTP (atualização
de switch, OLT, roteador…).

Layout, dentro de STORAGE_PATH:
    firmware/files/   o que é servido (raiz do login FTP de firmware; RRQ do TFTP)
    firmware/.tmp/    envios do painel em andamento (fora da raiz servida)
    firmware/.status/ conexões ativas publicadas pelos receptores (ftp.json, tftp.json)

Nada aqui é backup: é a única área que os receptores servem para leitura, e só ela. Os
arquivos são enviados pelo administrador no painel (página FTP Firmwares).
"""

import ipaddress
import json
import os
import tempfile
import time
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


# ------------------------------------------------- conexões ativas (monitor) --
#
# Os receptores não acessam o banco nem a API: cada um grava o próprio retrato das sessões
# de firmware em firmware/.status/<protocolo>.json (troca atômica) a cada STATUS_EVERY s.
# O painel lê esses arquivos; sem atualização há STATUS_STALE s, o receptor está fora do ar.

STATUS_EVERY = 2.0
STATUS_HEARTBEAT = 20.0
STATUS_STALE = 60.0


def status_dir() -> Path:
    return base_dir() / ".status"


class StatusPublisher:
    """Grava o retrato quando ele muda (ou a cada STATUS_HEARTBEAT s, como sinal de vida)."""

    def __init__(self, protocol: str) -> None:
        self.protocol = protocol
        self._last: list[dict] | None = None
        self._at = 0.0

    def publish(self, sessions: list[dict], force: bool = False) -> None:
        now = time.time()
        if not force and sessions == self._last and now - self._at < STATUS_HEARTBEAT:
            return
        d = status_dir()
        d.mkdir(parents=True, exist_ok=True)
        data = json.dumps({"updated_at": now, "sessions": sessions})
        fd, tmp = tempfile.mkstemp(dir=d, prefix=f".{self.protocol}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.chmod(tmp, 0o644)
            os.replace(tmp, d / f"{self.protocol}.json")
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self._last, self._at = sessions, now


def read_status(protocol: str) -> tuple[bool, datetime | None, list[dict]]:
    """(receptor no ar, última atualização, sessões). Fora do ar: sessões vazias."""
    try:
        data = json.loads((status_dir() / f"{protocol}.json").read_text(encoding="utf-8"))
        at = float(data["updated_at"])
        sessions = [s for s in data.get("sessions", []) if isinstance(s, dict)]
    except (OSError, ValueError, KeyError, TypeError):
        return False, None, []
    when = datetime.fromtimestamp(at, UTC).replace(tzinfo=None)
    if time.time() - at > STATUS_STALE:
        return False, when, []
    return True, when, sessions
