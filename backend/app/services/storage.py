"""Layout da pasta de backups (STORAGE_PATH, montada do host):

    incoming/<cliente>/<execução>/   área de upload (rsync via sshd, escrita apenas)
    store/<cliente>/<execução>/      backups aceitos pelo worker
    quarantine/<cliente>/<…>/        uploads rejeitados (manifesto inválido, incompletos)
"""

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


def root() -> Path:
    return Path(settings.storage_path)


def incoming() -> Path:
    return root() / "incoming"


def store() -> Path:
    return root() / "store"


def quarantine() -> Path:
    return root() / "quarantine"


def safe_child(base: Path, *names: str) -> Path:
    """Junta nomes vindos de fora (manifesto, banco) garantindo que o caminho
    final continua dentro de `base` — sem `..`, sem barras, sem links."""
    for n in names:
        if not SAFE_NAME.match(n) or n in (".", ".."):
            raise ValueError(f"nome inválido: {n!r}")
    p = base.joinpath(*names)
    if os.path.commonpath([str(base.resolve()), str(p.resolve())]) != str(base.resolve()):
        raise ValueError("caminho fora da área de armazenamento")
    return p


def ensure_layout() -> None:
    for d in (incoming(), store(), quarantine()):
        d.mkdir(parents=True, exist_ok=True)


def ensure_client_dirs(slug: str) -> None:
    """Cria incoming/<slug> (o rrsync do cliente falha se a pasta não existir)."""
    try:
        ensure_layout()
        d = safe_child(incoming(), slug)
        d.mkdir(mode=0o700, exist_ok=True)
        safe_child(store(), slug).mkdir(mode=0o700, exist_ok=True)
    except OSError:
        # dev/testes sem o volume montado — o worker recria no próximo ciclo
        pass


def remove_tree(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


@dataclass
class DiskUsage:
    total: int
    used: int
    free: int


def disk_usage() -> DiskUsage:
    try:
        u = shutil.disk_usage(root())
    except OSError:
        return DiskUsage(0, 0, 0)
    return DiskUsage(total=u.total, used=u.used, free=u.free)
