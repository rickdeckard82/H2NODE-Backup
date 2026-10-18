"""Arquivos para baixar no painel (Downloads): agentes e a chave pública.

- Agente Linux: um .tar.gz montado NA HORA a partir da pasta agent/ do repositório
  (montada só-leitura no backend em AGENT_DIR) — sempre a versão que está no servidor.
- Arquivos enviados pelo administrador (ex.: o instalador do Windows, compilado fora
  do servidor): ficam em STORAGE_PATH/downloads/.
- A chave pública GPG dos backups.

Links temporários (para `curl` no servidor do cliente, sem login): HMAC do nome + validade
com a JWT_SECRET. Os arquivos não são segredo, mas ficam atrás do login como o resto da
infraestrutura.
"""

import gzip
import hashlib
import hmac
import io
import re
import tarfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.services import gpg, storage

AGENT_FILES = (("pulse-backup-agent.sh", 0o755), ("install.sh", 0o755), ("agent.conf.example", 0o644))
KEY_NAME = "backup-key.pub.asc"
# o que pode ser enviado: instaladores e pacotes (nada de .html/.js servidos pelo domínio do painel)
UPLOAD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(exe|msi|zip|tar\.gz|tgz)$")
UPLOAD_MAX = 512 * 1024 * 1024
LINK_TTL = 3600

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


@dataclass
class Item:
    name: str
    title: str
    platform: str  # linux | windows | key | other
    source: str  # agent | uploaded | key
    size: int
    sha256: str
    updated_at: datetime
    version: str | None


def uploads_dir() -> Path:
    return storage.root() / "downloads"


def agent_dir() -> Path:
    return Path(settings.agent_dir)


def agent_version() -> str | None:
    try:
        text = (agent_dir() / "pulse-backup-agent.sh").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'^AGENT_VERSION="([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else None


_bundle_cache: dict[tuple, bytes] = {}


def agent_bundle() -> tuple[str, bytes, datetime] | None:
    """(nome, conteúdo, data) do pulse-backup-agent-<versão>.tar.gz, ou None sem agent/."""
    base = agent_dir()
    files = [(base / n, mode) for n, mode in AGENT_FILES]
    try:
        stats = [p.stat() for p, _ in files]
    except OSError:
        return None
    version = agent_version() or "dev"
    key = (version, *((s.st_mtime_ns, s.st_size) for s in stats))
    data = _bundle_cache.get(key)
    if data is None:
        raw = io.BytesIO()
        top = f"pulse-backup-agent-{version}"
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tf:
            for (p, mode), st in zip(files, stats, strict=True):
                info = tarfile.TarInfo(f"{top}/{p.name}")
                info.size, info.mode, info.mtime = st.st_size, mode, int(st.st_mtime)
                info.uname = info.gname = "root"
                tf.addfile(info, io.BytesIO(p.read_bytes()))
        # mtime=0: o mesmo agente gera sempre o mesmo arquivo (e o mesmo SHA-256)
        data = gzip.compress(raw.getvalue(), mtime=0)
        _bundle_cache.clear()
        _bundle_cache[key] = data
    when = datetime.fromtimestamp(max(s.st_mtime for s in stats), UTC).replace(tzinfo=None)
    return f"pulse-backup-agent-{version}.tar.gz", data, when


_sha_cache: dict[tuple, str] = {}


def _sha256_file(p: Path) -> str:
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    if key not in _sha_cache:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        _sha_cache[key] = h.hexdigest()
    return _sha_cache[key]


def _uploaded_title(name: str) -> tuple[str, str]:
    low = name.lower()
    if low.endswith((".exe", ".msi")):
        return "Cliente Windows (instalador)", "windows"
    return "Arquivo enviado", "other"


def list_items() -> list[Item]:
    items: list[Item] = []
    bundle = agent_bundle()
    if bundle:
        name, data, when = bundle
        items.append(Item(name, "Agente Linux (servidores e cPanel)", "linux", "agent", len(data),
                          hashlib.sha256(data).hexdigest(), when, agent_version()))
    d = uploads_dir()
    if d.is_dir():
        for p in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.is_symlink() or not p.is_file() or not UPLOAD_RE.match(p.name):
                continue
            title, platform = _uploaded_title(p.name)
            m = _VERSION_RE.search(p.name)
            items.append(Item(p.name, title, platform, "uploaded", p.stat().st_size, _sha256_file(p),
                              datetime.fromtimestamp(p.stat().st_mtime, UTC).replace(tzinfo=None),
                              m.group(1) if m else None))
    pub = gpg.public_key_info()
    if pub:
        data = pub.armored.encode()
        items.append(Item(KEY_NAME, "Chave pública GPG dos backups", "key", "key", len(data),
                          hashlib.sha256(data).hexdigest(), datetime.now(UTC).replace(tzinfo=None), None))
    return items


def open_item(name: str) -> tuple[bytes | Path, str] | None:
    """Conteúdo (bytes) ou caminho do arquivo + content-type; None se não existe."""
    if name == KEY_NAME:
        pub = gpg.public_key_info()
        return (pub.armored.encode(), "application/pgp-keys") if pub else None
    bundle = agent_bundle()
    if bundle and name == bundle[0]:
        return bundle[1], "application/gzip"
    if UPLOAD_RE.match(name):
        p = storage.safe_child(uploads_dir(), name)
        if p.is_file() and not p.is_symlink():
            exe = name.lower().endswith(".exe")
            return p, "application/vnd.microsoft.portable-executable" if exe else "application/octet-stream"
    return None


# ------------------------------------------------------------ links --

def _sig(name: str, exp: int) -> str:
    msg = f"download|{name}|{exp}".encode()
    return hmac.new(settings.jwt_secret.encode(), msg, hashlib.sha256).hexdigest()[:40]


def sign(name: str, ttl: int = LINK_TTL) -> tuple[str, int]:
    exp = int(time.time()) + ttl
    return f"{exp}.{_sig(name, exp)}", exp


def check(name: str, token: str) -> bool:
    exp_s, _, sig = token.partition(".")
    if not exp_s.isdigit() or int(exp_s) < time.time():
        return False
    return hmac.compare_digest(sig, _sig(name, int(exp_s)))
