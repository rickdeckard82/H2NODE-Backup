"""Coleta da configuração de MikroTik (RouterOS) por SSH — roda no serviço `puller`.

Diferente dos outros equipamentos (que ENVIAM por FTP/TFTP), aqui o H2NODE Backup
busca: conecta com o usuário de uma credencial (Configuração → MikroTik), roda
`/export show-sensitive` (RouterOS 7; no 6 cai para `/export`, que já inclui tudo),
valida, CIFRA em memória com a chave pública e grava em store/<equipamento>/.
Nada da configuração toca o disco em claro.

A chave de host SSH é fixada na primeira coleta; se mudar, a coleta para até alguém
aceitar a nova chave no painel (evita entregar a senha a um impostor).
"""

import base64
import hashlib
import logging
import secrets
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import paramiko
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import settings
from app.core.logging import logger
from app.core.security import utcnow
from app.models import Backup, BackupStatus, Client, DeviceCredential, VerifyStatus
from app.services import netconfig, netingest
from app.services.ingest import refresh_client_stats

AGENT_VERSION = "ssh-mikrotik"
EXPORT_CMD = "/export show-sensitive"
EXPORT_CMD_V6 = "/export"

logging.getLogger("paramiko").setLevel(logging.WARNING)


class PullError(Exception):
    pass


class HostKeyMismatch(PullError):
    pass


@dataclass(frozen=True)
class Job:
    client_id: int
    slug: str
    ip: str
    port: int
    username: str
    password: str
    pinned_host_key: str | None


@dataclass
class Export:
    data: bytes
    host_key: str
    command: str


def host_key_fingerprint(line: str | None) -> str | None:
    """'ssh-ed25519 AAAA…' -> 'SHA256:…' (o mesmo formato do ssh-keygen -l)."""
    if not line:
        return None
    try:
        blob = base64.b64decode(line.split()[1])
    except (IndexError, ValueError):
        return None
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def _is_ros_error(data: bytes) -> bool:
    if len(data) > 4096:
        return False
    low = data.decode("utf-8", errors="replace").lower()
    return any(e in low for e in netconfig.ROS_ERRORS)


def _run(t: paramiko.Transport, cmd: str, timeout: float, max_bytes: int) -> bytes:
    ch = t.open_session(timeout=timeout)
    try:
        ch.settimeout(timeout)  # sem nada chegar por `timeout` segundos = desiste
        ch.exec_command(cmd)
        deadline = time.monotonic() + timeout * 10
        buf = bytearray()
        while True:
            chunk = ch.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > max_bytes:
                raise PullError("exportação maior que o limite (NET_MAX_FILE_MB)")
            if time.monotonic() > deadline:
                raise PullError("tempo esgotado lendo a exportação")
        return bytes(buf)
    finally:
        ch.close()


def fetch_export(job: Job, timeout: float | None = None) -> Export:
    """Conecta, confere a chave de host, autentica e devolve a saída do /export.
    Só rede: não toca no banco (roda numa thread)."""
    timeout = timeout or settings.pull_timeout_seconds
    max_bytes = settings.net_max_file_mb * 1024 * 1024
    try:
        sock = socket.create_connection((job.ip, job.port), timeout=min(15.0, timeout))
    except OSError as exc:
        raise PullError(f"sem conexão com {job.ip}:{job.port} ({exc.strerror or exc})") from exc
    t = paramiko.Transport(sock)
    try:
        t.banner_timeout = timeout
        t.auth_timeout = timeout
        t.start_client(timeout=timeout)
        key = t.get_remote_server_key()
        line = f"{key.get_name()} {key.get_base64()}"
        if job.pinned_host_key and job.pinned_host_key != line:
            raise HostKeyMismatch(
                f"a chave de host SSH mudou (agora {host_key_fingerprint(line)}, fixada "
                f"{host_key_fingerprint(job.pinned_host_key)}) — se o equipamento foi trocado ou "
                "reinstalado, aceite a nova chave no painel"
            )
        try:
            t.auth_password(job.username, job.password)
        except paramiko.BadAuthenticationType as exc:
            if "keyboard-interactive" not in exc.allowed_types:
                allowed = ", ".join(exc.allowed_types)
                raise PullError(f"o equipamento não aceita senha (aceita: {allowed})") from exc
            t.auth_interactive(job.username, lambda _t, _i, prompts: [job.password] * len(prompts))
        if not t.is_authenticated():
            raise PullError("usuário ou senha recusados")
        cmd = EXPORT_CMD
        data = _run(t, cmd, timeout, max_bytes)
        if _is_ros_error(data):  # RouterOS 6 não conhece show-sensitive
            cmd = EXPORT_CMD_V6
            data = _run(t, cmd, timeout, max_bytes)
        return Export(data=data, host_key=line, command=cmd)
    except paramiko.AuthenticationException as exc:
        raise PullError("usuário ou senha recusados") from exc
    except TimeoutError as exc:
        raise PullError("tempo esgotado (o equipamento não respondeu)") from exc
    except paramiko.SSHException as exc:
        raise PullError(f"erro SSH: {exc}") from exc
    except OSError as exc:
        raise PullError(f"erro de rede: {exc}") from exc
    finally:
        t.close()


# ------------------------------------------------------------------ banco --


def _interval(c: Client) -> timedelta:
    return timedelta(hours=max(1, c.expected_interval_hours))


def claim_due(db: Session, now: datetime | None = None) -> list[Job]:
    """MikroTiks ativos com coleta vencida. Já agenda a próxima (se o puller cair no
    meio, não fica tentando em laço)."""
    now = now or utcnow()
    rows = db.execute(
        select(Client, DeviceCredential)
        .join(DeviceCredential, DeviceCredential.id == Client.pull_credential_id)
        .where(
            Client.kind == "network", Client.protocol == "ssh", Client.is_active.is_(True),
            Client.mgmt_ip.is_not(None),
            or_(Client.pull_next_at.is_(None), Client.pull_next_at <= now),
        )
        .order_by(Client.pull_next_at.nulls_first(), Client.id)
    ).all()
    jobs: list[Job] = []
    for c, cred in rows:
        c.pull_next_at = now + _interval(c)
        try:
            password = crypto.decrypt(cred.password_enc)
        except Exception:  # noqa: BLE001  (FERNET_KEY trocada)
            c.pull_error = ("não foi possível decifrar a senha da credencial (FERNET_KEY mudou?) — "
                            "salve-a de novo")
            continue
        jobs.append(Job(client_id=c.id, slug=c.slug, ip=c.mgmt_ip or "", port=c.pull_port or cred.port,
                        username=cred.username, password=password, pinned_host_key=c.pull_host_key))
    db.commit()
    return jobs


def _record_failure(db: Session, c: Client, message: str, now: datetime) -> None:
    db.add(Backup(
        client_id=c.id, run_name=f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}",
        status=BackupStatus.failed, agent_status="failed", started_at=now, finished_at=now,
        received_at=now, storage_path=None, agent_version=AGENT_VERSION,
        error_message=f"coleta SSH de {c.mgmt_ip}: {message}"[:2000],
        manifest={"format": "h2node-backup/net-1", "protocol": "ssh", "source_ip": c.mgmt_ip,
                  "status": "failed", "errors": [message]},
        verify_status=VerifyStatus.skipped,
    ))
    c.last_backup_at = now
    c.last_status = BackupStatus.failed.value
    db.flush()
    refresh_client_stats(db, c)


def record(db: Session, job: Job, result: Export | BaseException) -> None:
    c = db.get(Client, job.client_id)
    if c is None:
        return
    now = utcnow()
    c.pull_last_at = now
    if isinstance(result, Export):
        try:
            netingest.store_config(
                db, c, result.data, f"{c.slug}.rsc", when=now, protocol="ssh", source_ip=job.ip,
                remote_path=result.command, agent_version=AGENT_VERSION,
            )
        except netingest.NoPublicKey:
            db.rollback()
            c = db.get(Client, job.client_id)
            assert c is not None
            c.pull_last_at = now
            c.pull_error = "chave pública GPG ausente no servidor — nada foi guardado"
            c.pull_next_at = now + timedelta(minutes=10)
            db.commit()
            logger.error("mikrotik_no_public_key", device=job.slug)
            return
        if not c.pull_host_key:
            c.pull_host_key = result.host_key  # TOFU: fixa na primeira coleta bem-sucedida
        c.pull_error = None
        db.commit()
        logger.info("mikrotik_pull_ok", device=job.slug, bytes=len(result.data), command=result.command)
        return
    msg = str(result) if isinstance(result, PullError) else f"erro interno: {result}"
    c.pull_error = msg[:2000]
    _record_failure(db, c, msg, now)
    db.commit()
    logger.warning("mikrotik_pull_failed", device=job.slug, error=msg)
