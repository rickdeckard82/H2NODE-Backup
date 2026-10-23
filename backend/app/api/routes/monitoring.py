"""Integração com Zabbix (ou outro monitoramento): o monitor CONSULTA o estado (pull).

- GET /monitoring/status — JSON com a saúde de cada cliente ativo, do worker e do disco, para o
  template "Pulse Backup by HTTP" (zabbix/). Autenticação: `Authorization: Bearer <token>`;
  só leitura; sem token configurado responde 404.
- /monitoring/settings e /monitoring/token — configuração no painel (administrador).

Os códigos numéricos (health_code, verify_code) são o contrato com os gatilhos do template:
não reordene; acrescente valores novos no fim.
"""

import hashlib
import hmac
import ipaddress
import secrets
import time
from importlib import metadata

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, enforce_csrf, require_admin
from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import limiter
from app.core.security import utcnow
from app.models import Backup, Client, MonitoringSettings, SystemUser, WorkerStatus
from app.schemas.common import UtcDatetime
from app.services import audit, firmware, storage
from app.services.health import client_health

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

TOKEN_PREFIX = "pbm_"
HEALTH_CODE = {"ok": 0, "warning": 1, "failed": 2, "overdue": 3, "never": 4}
VERIFY_CODE = {"ok": 0, "pending": 1, "running": 1, "failed": 2, "skipped": 3}
VERIFY_NONE = 3


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _version() -> str:
    try:
        return metadata.version("pulse-backup-backend")
    except metadata.PackageNotFoundError:
        return ""


def _age(dt) -> int:  # noqa: ANN001
    return max(0, int((utcnow() - dt).total_seconds())) if dt else -1


def _allowed(ip: str | None, networks: str) -> bool:
    nets = [n for n in (networks or "").splitlines() if n.strip()]
    if not nets:
        return True
    try:
        addr = ipaddress.ip_address((ip or "").removeprefix("::ffff:"))
    except ValueError:
        return False
    for n in nets:
        try:
            net = ipaddress.ip_network(n, strict=False)
        except ValueError:
            continue
        if addr.version == net.version and addr in net:
            return True
    return False


def _authorize(request: Request, db: Session) -> MonitoringSettings:
    row = db.get(MonitoringSettings, 1)
    if row is None or not row.token_hash:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "monitoramento não configurado")
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(_hash(token.strip()), row.token_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido",
                            headers={"WWW-Authenticate": "Bearer"})
    ip = client_ip(request)
    if not _allowed(ip, row.allowed_networks):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "IP não autorizado para o monitoramento")
    row.last_used_at, row.last_used_ip = utcnow(), ip
    return row


@router.get("/status")
@limiter.limit("60/minute")
def monitoring_status(request: Request, db: Session = Depends(get_db)) -> dict:
    _authorize(request, db)
    latest_ids = select(func.max(Backup.id)).where(Backup.deleted_at.is_(None)).group_by(Backup.client_id)
    latest = {b.client_id: b for b in db.execute(select(Backup).where(Backup.id.in_(latest_ids))).scalars()}
    clients = []
    summary = dict.fromkeys(HEALTH_CODE, 0)
    for c in db.execute(select(Client).where(Client.is_active.is_(True)).order_by(Client.slug)).scalars():
        health = client_health(c)
        summary[health] = summary.get(health, 0) + 1
        b = latest.get(c.id)
        verify = b.verify_status.value if b else ""
        error = ""
        if b and b.status.value in ("failed", "corrupted", "warning"):
            error = b.error_message or ""
        if b and verify == "failed":
            error = error or b.verify_message or ""
        if not error and c.pull_error:
            error = c.pull_error
        clients.append({
            "slug": c.slug,
            "name": c.name,
            "kind": c.kind,
            "vendor": c.vendor or "",
            "health": health,
            "health_code": HEALTH_CODE.get(health, 2),
            "last_backup_at": c.last_backup_at.isoformat() + "Z" if c.last_backup_at else None,
            "last_backup_age": _age(c.last_backup_at),
            "last_status": c.last_status or "",
            "verify_status": verify,
            "verify_code": VERIFY_CODE.get(verify, VERIFY_NONE),
            "last_size": b.size_bytes if b else 0,
            "expected_interval_hours": c.expected_interval_hours,
            "error": " ".join(error.split())[:255],
        })
    ws = db.get(WorkerStatus, 1)
    disk = storage.disk_usage()
    db.commit()  # last_used_at
    return {
        "version": _version(),
        "generated_at": int(time.time()),
        "worker": {
            # sinal de vida (thread a cada 30 s, também no meio de tarefas longas)
            "last_seen_age": _age(ws.last_seen_at) if ws else -1,
            "deep_verify": 1 if ws and ws.deep_verify else 0,
            # tarefa atual: "" e -1 = ocioso
            "busy_with": (ws.busy_with or "") if ws else "",
            "busy_age": _age(ws.busy_since) if ws and ws.busy_with else -1,
        },
        "disk": {
            "total": disk.total, "used": disk.used, "free": disk.free,
            "pused": round(disk.used * 100 / disk.total, 2) if disk.total else 0,
        },
        "summary": summary,
        "clients": clients,
    }


# ---------------------------------------------------------------- painel --


class MonitoringOut(BaseModel):
    configured: bool
    token_hint: str | None
    allowed_networks: list[str]
    last_used_at: UtcDatetime | None
    last_used_ip: str | None
    status_url: str


class MonitoringIn(BaseModel):
    allowed_networks: list[str] = Field(default_factory=list, max_length=100)


class TokenOut(BaseModel):
    token: str
    settings: MonitoringOut


def _row(db: Session) -> MonitoringSettings:
    row = db.get(MonitoringSettings, 1)
    if row is None:
        row = MonitoringSettings(id=1, allowed_networks="")
        db.add(row)
        db.flush()
    return row


def _out(row: MonitoringSettings | None) -> MonitoringOut:
    url = f"{settings.frontend_origin.rstrip('/')}{settings.api_prefix}/monitoring/status"
    if row is None:
        return MonitoringOut(configured=False, token_hint=None, allowed_networks=[], last_used_at=None,
                             last_used_ip=None, status_url=url)
    return MonitoringOut(
        configured=bool(row.token_hash), token_hint=row.token_hint,
        allowed_networks=[n for n in (row.allowed_networks or "").splitlines() if n.strip()],
        last_used_at=row.last_used_at, last_used_ip=row.last_used_ip, status_url=url,
    )


def _audit(db: Session, request: Request, actor: SystemUser, action: str, after: dict | None = None) -> None:
    audit.record(db, action=action, entity_type="monitoring", entity_id=1, actor_id=actor.id,
                 actor_username=actor.username, ip_address=client_ip(request), after=after)


@router.get("/settings", response_model=MonitoringOut)
def get_settings(db: Session = Depends(get_db), _: SystemUser = Depends(require_admin)) -> MonitoringOut:
    return _out(db.get(MonitoringSettings, 1))


@router.put("/settings", response_model=MonitoringOut, dependencies=[Depends(enforce_csrf)])
def update_settings(body: MonitoringIn, request: Request, db: Session = Depends(get_db),
                    actor: SystemUser = Depends(require_admin)) -> MonitoringOut:
    try:
        nets = firmware.parse_networks(body.allowed_networks)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    row = _row(db)
    row.allowed_networks = "\n".join(nets)
    _audit(db, request, actor, "update", {"allowed_networks": nets})
    db.commit()
    return _out(row)


@router.post("/token", response_model=TokenOut, dependencies=[Depends(enforce_csrf)])
def new_token(request: Request, db: Session = Depends(get_db),
              actor: SystemUser = Depends(require_admin)) -> TokenOut:
    """Gera (ou troca) o token do Zabbix. Mostrado só nesta resposta; o anterior deixa de valer."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = _row(db)
    replaced = bool(row.token_hash)
    row.token_hash, row.token_hint = _hash(token), token[-6:]
    row.last_used_at = row.last_used_ip = None
    _audit(db, request, actor, "create_token", {"replaced": replaced})
    db.commit()
    return TokenOut(token=token, settings=_out(row))


@router.delete("/token", response_model=MonitoringOut, dependencies=[Depends(enforce_csrf)])
def revoke_token(request: Request, db: Session = Depends(get_db),
                 actor: SystemUser = Depends(require_admin)) -> MonitoringOut:
    row = _row(db)
    row.token_hash = row.token_hint = None
    _audit(db, request, actor, "revoke_token")
    db.commit()
    return _out(row)
