"""Ponte entre o painel e os receptores FTP/TFTP (containers na rede do host,
sem acesso ao banco).

O painel/worker grava `receivers.json` no volume compartilhado com:
  - equipamentos ATIVOS (slug, IP de origem, protocolo e, no FTP, a conta presa ao
    cadastro — um IP pode ter vários cadastros FTP, um por conta);
  - contas FTP ATIVAS (usuário + hash Argon2id da senha);
  - o servidor de firmwares, se ativo: login FTP próprio e IPs/redes que podem BAIXAR
    de STORAGE_PATH/firmware/files (a única área servida para leitura).
Os receptores recarregam o arquivo quando ele muda.

Layout da recepção, dentro de STORAGE_PATH:
    netin/.sessions/<slug>/<sessão>/   área de escrita de uma sessão FTP
    netin/.tmp/                        transferências TFTP em andamento
    netin/<slug>/<carimbo>__<nome>     arquivo completo, pronto para o worker
    netin/<slug>/<carimbo>__<nome>.meta.json   (gravado por ÚLTIMO)
"""

import ipaddress
import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger

ALLOWLIST_FILE = "receivers.json"
META_SUFFIX = ".meta.json"


def shared_dir() -> Path:
    return Path(settings.receivers_shared_dir)


def netin() -> Path:
    return Path(settings.storage_path) / "netin"


def render(db: Session) -> dict:
    from app.models import Client, FirmwareSettings, FtpAccount

    users = {a.id: a.username for a in db.execute(select(FtpAccount)).scalars()}
    devices = [
        {"slug": c.slug, "ip": c.mgmt_ip, "protocol": c.protocol, "vendor": c.vendor,
         "ftp_user": users.get(c.ftp_account_id) if c.ftp_account_id else None}
        for c in db.execute(
            select(Client).where(Client.kind == "network", Client.is_active.is_(True))
        ).scalars()
        # ssh (MikroTik) é coletado pelo puller: esse IP não ganha acesso aos receptores
        if c.mgmt_ip and c.protocol in ("ftp", "tftp")
    ]
    accounts = [
        {"username": a.username, "password_hash": a.password_hash}
        for a in db.execute(select(FtpAccount).where(FtpAccount.is_active.is_(True))).scalars()
    ]
    # IPs de UNM2000 (gerenciador) informados nas OLTs Fiberhome: entram no FTP sem ser equipamento
    managers = sorted({
        c.manager_ip
        for c in db.execute(
            select(Client).where(Client.kind == "network", Client.is_active.is_(True),
                                 Client.manager_ip.is_not(None))
        ).scalars()
        if c.manager_ip and c.protocol == "ftp"
    })
    return {"version": 1, "devices": devices, "ftp_accounts": accounts, "managers": managers,
            "firmware": _render_firmware(db, FirmwareSettings, Client)}


def _render_firmware(db: Session, model, client_model) -> dict | None:  # noqa: ANN001
    fw = db.get(model, 1)
    if fw is None or not fw.enabled:
        return None
    ips: list[str] = []
    if fw.include_devices:
        ips = sorted({
            c.mgmt_ip
            for c in db.execute(
                select(client_model).where(client_model.kind == "network", client_model.is_active.is_(True))
            ).scalars()
            if c.mgmt_ip
        })
    has_login = bool(fw.ftp_username and fw.ftp_password_hash)
    return {
        "ftp_user": fw.ftp_username if has_login else None,
        "password_hash": fw.ftp_password_hash if has_login else None,
        "networks": [n for n in (fw.allowed_networks or "").splitlines() if n.strip()],
        "ips": ips,
    }


def sync(db: Session) -> bool:
    """Reescreve receivers.json de forma atômica (modo 600: tem hashes de senha)."""
    d = shared_dir()
    if not d.is_dir():
        logger.warning("receivers_shared_dir_missing", path=str(d))
        return False
    data = json.dumps(render(db), indent=1)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".receivers.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, d / ALLOWLIST_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


# ---------------------------------------------------------------- receptores --


# Tipo "Arquivos e bancos": servidor/serviço que envia dumps e arquivos (limite NET_FILES_MAX_MB).
FILES_VENDOR = "files"

# Fabricante interno dado ao IP da UNM2000 (não é selecionável no cadastro).
MANAGER_VENDOR = "unm2000"
MANAGER_SLUG = "unm2000"


@dataclass(frozen=True)
class Device:
    slug: str
    ip: str
    protocol: str
    vendor: str | None
    # FTP: só esta conta envia por este cadastro (None = qualquer conta)
    ftp_user: str | None = None


class Allowlist:
    """Leitura do receivers.json com recarga automática quando o arquivo muda."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (shared_dir() / ALLOWLIST_FILE)
        self._mtime: float | None = None
        self.by_ip: dict[str, list[Device]] = {}
        self.managers: set[str] = set()
        self.accounts: dict[str, str] = {}
        # servidor de firmwares (só leitura): login FTP e quem pode baixar
        self.fw_user: str | None = None
        self.fw_hash: str | None = None
        self.fw_nets: list = []
        self.fw_ips: set[str] = set()

    def refresh(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self.by_ip, self.accounts, self.managers, self._mtime = {}, {}, set(), None
            self.fw_user, self.fw_hash, self.fw_nets, self.fw_ips = None, None, [], set()
            return
        if mtime == self._mtime:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error("receivers_allowlist_unreadable", error=str(exc))
            return
        by_ip: dict[str, list[Device]] = {}
        for d in data.get("devices", []):
            by_ip.setdefault(d["ip"], []).append(
                Device(d["slug"], d["ip"], d["protocol"], d.get("vendor"), d.get("ftp_user"))
            )
        self.by_ip = by_ip
        self.accounts = {a["username"]: a["password_hash"] for a in data.get("ftp_accounts", [])}
        self.managers = {m for m in data.get("managers", []) if isinstance(m, str)}
        fw = data.get("firmware") or {}
        self.fw_user = fw.get("ftp_user") or None
        self.fw_hash = fw.get("password_hash") or None
        nets = []
        for n in fw.get("networks", []):
            try:
                nets.append(ipaddress.ip_network(n, strict=False))
            except ValueError:
                logger.warning("firmware_network_invalid", network=str(n)[:64])
        self.fw_nets = nets
        self.fw_ips = {i for i in fw.get("ips", []) if isinstance(i, str)}
        self._mtime = mtime
        logger.info("receivers_allowlist_loaded", devices=len(self.by_ip), accounts=len(self.accounts),
                    managers=len(self.managers))

    def device(self, ip: str, protocol: str, username: str | None = None) -> Device | None:
        """Cadastro que recebe o envio deste IP. Sem `username` (antes do login FTP), qualquer
        cadastro do IP serve só para aceitar a conexão. No login FTP, a conta escolhe entre os
        cadastros do IP: o preso a ela ou, se for o único do IP, o sem conta presa."""
        self.refresh()
        # IPv4 mapeado em IPv6 (::ffff:10.0.0.1) quando o socket é dual-stack
        if ip.startswith("::ffff:"):
            ip = ip[7:]
        cands = [d for d in self.by_ip.get(ip, []) if d.protocol == protocol]
        if protocol == "ftp" and username is not None:
            bound = [d for d in cands if d.ftp_user == username]
            if bound:
                return bound[0]
            cands = cands if len(cands) == 1 and cands[0].ftp_user is None else []
        if cands:
            return cands[0]
        if protocol == "ftp" and ip in self.managers:
            return Device(MANAGER_SLUG, ip, "ftp", MANAGER_VENDOR)
        return None

    def firmware_allows(self, ip: str) -> bool:
        """Este IP pode baixar firmware (FTP com o login de firmware, TFTP RRQ)?"""
        self.refresh()
        if ip.startswith("::ffff:"):
            ip = ip[7:]
        if ip in self.fw_ips:
            return True
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr.version == n.version and addr in n for n in self.fw_nets)

    def is_firmware_user(self, username: str) -> bool:
        self.refresh()
        return self.fw_user is not None and username == self.fw_user


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(remote_path: str) -> str:
    """'DM4380MP/config.txt' -> 'DM4380MP_config.txt' (sem barras, sem ponto inicial)."""
    name = _UNSAFE.sub("_", remote_path.replace("\\", "/").strip("/")).strip("._-")
    return (name or "config")[:120]


def finalize(src: Path, device: Device, *, protocol: str, remote_path: str, size: int) -> Path:
    """Move um upload completo para netin/<slug>/ e grava o .meta.json por último
    (é ele que sinaliza ao worker que o arquivo está pronto)."""
    now = datetime.now(UTC)
    dest_dir = netin() / device.slug
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}__{safe_filename(remote_path)}"
    dest = dest_dir / base
    os.replace(src, dest)
    meta = {
        "device": device.slug,
        "source_ip": device.ip,
        "protocol": protocol,
        "remote_path": remote_path[:500],
        "size": size,
        "received_at": now.isoformat(),
    }
    fd, tmp = tempfile.mkstemp(dir=dest_dir, prefix=".meta.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    os.replace(tmp, dest_dir / (base + META_SUFFIX))
    logger.info("net_upload_received", device=device.slug, protocol=protocol, file=remote_path, size=size)
    return dest


def finalize_batch(files: list[tuple[Path, str]], device: Device, *, protocol: str) -> Path | None:
    """Move os arquivos completos de UMA sessão (lista de (caminho, caminho remoto)) para
    netin/<slug>/<carimbo>__lote/ e grava um único .meta.json por último: o worker registra
    tudo como uma execução com uma parte por arquivo (tipo "Arquivos e bancos")."""
    if not files:
        return None
    now = datetime.now(UTC)
    dest_dir = netin() / device.slug
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}__lote"
    batch = dest_dir / base
    batch.mkdir(mode=0o700)
    entries, used = [], set()
    for i, (src, remote_path) in enumerate(files, 1):
        name = safe_filename(remote_path)
        if name in used:
            name = f"{i:02d}_{name}"
        used.add(name)
        size = src.stat().st_size
        os.replace(src, batch / name)
        entries.append({"name": name, "remote_path": remote_path[:500], "size": size})
    meta = {
        "device": device.slug,
        "source_ip": device.ip,
        "protocol": protocol,
        "files": entries,
        "received_at": now.isoformat(),
    }
    fd, tmp = tempfile.mkstemp(dir=dest_dir, prefix=".meta.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    os.replace(tmp, dest_dir / (base + META_SUFFIX))
    logger.info("net_upload_batch_received", device=device.slug, protocol=protocol,
                files=[e["remote_path"] for e in entries], size=sum(e["size"] for e in entries))
    return batch


def drop_privileges(uid: int = 10001, gid: int = 10001) -> None:
    """Depois de abrir as portas < 1024, roda como o usuário sem privilégio."""
    if os.getuid() != 0:
        return
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    os.umask(0o077)
