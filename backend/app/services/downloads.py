"""Arquivos para baixar no painel (Downloads): agentes e a chave pública.

- Agente Linux: um .tar.gz montado NA HORA a partir da pasta agent/ do repositório
  (montada só-leitura no backend em AGENT_DIR) — sempre a versão que está no servidor.
- Instalador do cliente Windows: compilado pelo serviço client-builder a cada
  `docker compose build` em que windows-client/ mudou; chega em CLIENT_DIST_DIR (só-leitura).
- Arquivos enviados pelo administrador: ficam em STORAGE_PATH/downloads/.
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
from app.core.logging import logger
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
    source: str  # agent | build | uploaded | key
    size: int
    sha256: str
    updated_at: datetime
    version: str | None


def uploads_dir() -> Path:
    return storage.root() / "downloads"


def agent_dir() -> Path:
    return Path(settings.agent_dir)


def build_dir() -> Path:
    return Path(settings.client_dist_dir)


def _files(d: Path) -> list[Path]:
    """Arquivos publicáveis de uma pasta, do mais novo para o mais antigo."""
    if not d.is_dir():
        return []
    ok = [p for p in d.iterdir() if not p.is_symlink() and p.is_file() and UPLOAD_RE.match(p.name)]
    return sorted(ok, key=lambda x: x.stat().st_mtime, reverse=True)


def built_names() -> set[str]:
    return {p.name for p in _files(build_dir())}


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


def _problem(problems: list[str], what: str, e: OSError) -> None:
    where = f" em {e.filename}" if e.filename else ""
    reason = "sem permissão de leitura" if isinstance(e, PermissionError) else (e.strerror or str(e))
    problems.append(f"{what}: {reason}{where}")
    logger.warning("download_unreadable", what=what, error=str(e))


def _vkey(v: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split(".")) if v else ()


def _latest_windows(items: list[Item]) -> list[Item]:
    """Só o instalador do Windows mais novo (o compilado ganha empate); versões antigas
    enviadas à mão ficam escondidas — o administrador pode excluí-las do disco antes."""
    win = [i for i in items if i.platform == "windows"]
    if len(win) < 2:
        return items
    best = max(win, key=lambda i: (_vkey(i.version), i.source == "build", i.updated_at))
    return [i for i in items if i.platform != "windows" or i is best]


def list_items() -> tuple[list[Item], list[str]]:
    """Itens disponíveis e os problemas encontrados (um arquivo ilegível não esconde os outros)."""
    items: list[Item] = []
    problems: list[str] = []
    try:
        bundle = agent_bundle()
    except OSError as e:
        bundle = None
        _problem(problems, f"agente Linux ({settings.agent_dir})", e)
    if bundle:
        name, data, when = bundle
        items.append(Item(name, "Agente Linux (servidores e cPanel)", "linux", "agent", len(data),
                          hashlib.sha256(data).hexdigest(), when, agent_version()))
    built: list[Path] = []
    uploaded: list[Path] = []
    try:
        built = _files(build_dir())
    except OSError as e:
        _problem(problems, f"instalador compilado ({settings.client_dist_dir})", e)
    try:
        uploaded = _files(uploads_dir())
    except OSError as e:
        _problem(problems, "arquivos enviados", e)
    seen = {p.name for p in built}
    files = [(p, "build") for p in built] + [(p, "uploaded") for p in uploaded if p.name not in seen]
    for p, source in files:
        title, platform = _uploaded_title(p.name)
        m = _VERSION_RE.search(p.name)
        try:
            st = p.stat()
            sha = _sha256_file(p)
        except OSError as e:
            _problem(problems, p.name, e)
            continue
        items.append(Item(p.name, title, platform, source, st.st_size, sha,
                          datetime.fromtimestamp(st.st_mtime, UTC).replace(tzinfo=None),
                          m.group(1) if m else None))
    items = _latest_windows(items)
    try:
        pub = gpg.public_key_info()
    except OSError as e:
        pub = None
        _problem(problems, f"chave pública ({settings.backup_public_key_path})", e)
    if pub:
        data = pub.armored.encode()
        items.append(Item(KEY_NAME, "Chave pública GPG dos backups", "key", "key", len(data),
                          hashlib.sha256(data).hexdigest(), datetime.now(UTC).replace(tzinfo=None), None))
    return items, problems


def open_item(name: str) -> tuple[bytes | Path, str] | None:
    """Conteúdo (bytes) ou caminho do arquivo + content-type; None se não existe."""
    if name == KEY_NAME:
        pub = gpg.public_key_info()
        return (pub.armored.encode(), "application/pgp-keys") if pub else None
    bundle = agent_bundle()
    if bundle and name == bundle[0]:
        return bundle[1], "application/gzip"
    if UPLOAD_RE.match(name):
        for d in (build_dir(), uploads_dir()):
            p = storage.safe_child(d, name)
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
