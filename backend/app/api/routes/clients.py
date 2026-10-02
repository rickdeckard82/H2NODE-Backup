from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, enforce_csrf, require_admin, require_auditor, require_operator
from app.core.config import settings
from app.core.db import get_db
from app.models import Backup, Client, SystemUser
from app.schemas.client import AgentConfigOut, ClientCreate, ClientOut, ClientUpdate
from app.services import audit, gpg, sshkeys, storage
from app.services.health import client_health

router = APIRouter(prefix="/clients", tags=["clients"], dependencies=[Depends(enforce_csrf)])


def _to_out(db: Session, c: Client) -> ClientOut:
    out = ClientOut.model_validate(c)
    out.backup_count = db.execute(
        select(func.count()).select_from(Backup).where(
            Backup.client_id == c.id, Backup.deleted_at.is_(None), Backup.storage_path.is_not(None)
        )
    ).scalar_one()
    out.health = client_health(c)
    return out


def _apply_key(c: Client, key: str | None) -> None:
    if key is None:
        return
    if not key.strip():
        c.ssh_public_key = None
        c.ssh_key_fingerprint = None
        return
    try:
        line, fp = sshkeys.parse_public_key(key)
    except sshkeys.InvalidSshKey as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    c.ssh_public_key = line
    c.ssh_key_fingerprint = fp


def _check_key_unique(db: Session, c: Client) -> None:
    if c.ssh_key_fingerprint and db.execute(
        select(Client.id).where(
            Client.ssh_key_fingerprint == c.ssh_key_fingerprint, Client.id != (c.id or 0)
        )
    ).first():
        # A mesma chave em dois clientes deixaria o sshd usar só a primeira linha.
        raise HTTPException(status.HTTP_409_CONFLICT, "esta chave SSH já pertence a outro cliente")


@router.get("", response_model=list[ClientOut])
def list_clients(
    db: Session = Depends(get_db),
    _: SystemUser = Depends(require_auditor),
    q: str | None = Query(None, max_length=100),
) -> list[ClientOut]:
    stmt = select(Client)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Client.name.ilike(like), Client.slug.ilike(like),
                              Client.hostname.ilike(like)))
    return [_to_out(db, c) for c in db.execute(stmt.order_by(Client.name)).scalars()]


@router.get("/{client_id}", response_model=ClientOut)
def get_client(
    client_id: int, db: Session = Depends(get_db), _: SystemUser = Depends(require_auditor)
) -> ClientOut:
    c = db.get(Client, client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    return _to_out(db, c)


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def create_client(
    body: ClientCreate, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_operator),
) -> ClientOut:
    if db.execute(select(Client.id).where(Client.slug == body.slug)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "já existe um cliente com este identificador")
    c = Client(
        slug=body.slug, name=body.name, description=body.description, is_active=body.is_active,
        expected_interval_hours=body.expected_interval_hours,
        retention_days=body.retention_days, retention_min_keep=body.retention_min_keep,
    )
    _apply_key(c, body.ssh_public_key)
    _check_key_unique(db, c)
    db.add(c)
    db.flush()
    audit.record(db, action="create", entity_type="client", entity_id=c.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 after={"slug": c.slug, "name": c.name, "ssh_key": c.ssh_key_fingerprint})
    db.commit()
    storage.ensure_client_dirs(c.slug)
    sshkeys.sync_authorized_keys(db)
    return _to_out(db, c)


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(
    client_id: int, body: ClientUpdate, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_operator),
) -> ClientOut:
    c = db.get(Client, client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    before = {"name": c.name, "is_active": c.is_active, "ssh_key": c.ssh_key_fingerprint,
              "retention_days": c.retention_days, "retention_min_keep": c.retention_min_keep,
              "expected_interval_hours": c.expected_interval_hours}
    for field in ("name", "description", "is_active", "expected_interval_hours",
                  "retention_days", "retention_min_keep"):
        v = getattr(body, field)
        if v is not None:
            setattr(c, field, v)
    _apply_key(c, body.ssh_public_key)
    _check_key_unique(db, c)
    audit.record(db, action="update", entity_type="client", entity_id=c.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 before=before,
                 after={"name": c.name, "is_active": c.is_active, "ssh_key": c.ssh_key_fingerprint,
                        "retention_days": c.retention_days, "retention_min_keep": c.retention_min_keep,
                        "expected_interval_hours": c.expected_interval_hours})
    db.commit()
    sshkeys.sync_authorized_keys(db)
    return _to_out(db, c)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(
    client_id: int, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_admin),
) -> None:
    """Remove o cadastro e o acesso SSH. Os backups já guardados NÃO são apagados
    do disco aqui (exclua-os antes pela tela de backups, se for o caso)."""
    c = db.get(Client, client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    stored = db.execute(
        select(func.count()).select_from(Backup).where(
            Backup.client_id == c.id, Backup.deleted_at.is_(None), Backup.storage_path.is_not(None)
        )
    ).scalar_one()
    if stored:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"o cliente ainda tem {stored} backup(s) guardado(s) — desative-o ou exclua os backups antes",
        )
    db.delete(c)
    audit.record(db, action="delete", entity_type="client", entity_id=client_id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 before={"slug": c.slug, "name": c.name})
    db.commit()
    sshkeys.sync_authorized_keys(db)


def render_agent_config(c: Client, fingerprint: str | None) -> str:
    return f"""# /etc/pulse-backup/agent.conf — gerado pelo Pulse Backup para "{c.name}"
# Permissões obrigatórias: dono root, modo 600 (o agente se recusa a rodar se não for).

CLIENT_ID="{c.slug}"
SERVER_HOST="{settings.ssh_public_host}"
SERVER_PORT="{settings.ssh_public_port}"
SERVER_USER="{settings.ssh_user}"
SSH_KEY="/etc/pulse-backup/id_ed25519"
KNOWN_HOSTS="/etc/pulse-backup/known_hosts"

# Chave pública GPG do servidor (baixe em Configuração → Chaves e servidor).
GPG_PUBLIC_KEY="/etc/pulse-backup/backup-key.pub.asc"
# O agente confere a chave antes de cifrar — evita cifrar para a chave errada.
GPG_FINGERPRINT="{fingerprint or 'PREENCHA-COM-A-IMPRESSAO-DIGITAL'}"

# Pasta temporária local (só arquivos JÁ cifrados ficam aqui; apagados ao final).
WORK_DIR="/var/tmp/pulse-backup"

# ---- Pastas ----
BACKUP_PATHS=(
  "/etc"
  # "/var/www"
  # "/home"
)
EXCLUDES=(
  # "/var/www/*/cache"
  # "*.tmp"
)
ONE_FILE_SYSTEM="no"

# ---- MySQL / MariaDB ----  (autenticação: unix_socket do root ou MYSQL_DEFAULTS_FILE)
MYSQL_ENABLED="no"
MYSQL_DATABASES=( "all" )
MYSQL_DEFAULTS_FILE=""          # ex.: /etc/pulse-backup/mysql.cnf ([client] user/password), modo 600
MYSQL_DUMP_OPTS=""

# ---- PostgreSQL ----  (roda pg_dump como o usuário do SO abaixo, via peer)
POSTGRES_ENABLED="no"
POSTGRES_DATABASES=( "all" )
POSTGRES_OS_USER="postgres"
POSTGRES_GLOBALS="yes"          # inclui roles/tablespaces (pg_dumpall --globals-only)

# ---- SQL Server (mssql-server para Linux) ----
MSSQL_ENABLED="no"
MSSQL_DATABASES=( "all" )
MSSQL_SERVER="localhost"
MSSQL_USER="sa"
MSSQL_PASSWORD_FILE="/etc/pulse-backup/mssql.pass"   # modo 600
MSSQL_BACKUP_DIR="/var/opt/mssql/data/pulse-backup" # gravável pelo usuário mssql

# ---- Envio ----
BWLIMIT=""                      # KB/s (vazio = sem limite)
UPLOAD_RETRIES="3"
LOG_FILE="/var/log/pulse-backup.log"
"""


@router.get("/{client_id}/agent-config", response_model=AgentConfigOut)
def agent_config(
    client_id: int, db: Session = Depends(get_db), _: SystemUser = Depends(require_operator)
) -> AgentConfigOut:
    c = db.get(Client, client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    pub = gpg.public_key_info()
    host_line, _fp = sshkeys.host_key()
    return AgentConfigOut(
        filename="agent.conf",
        content=render_agent_config(c, pub.fingerprint if pub else None),
        known_hosts=sshkeys.known_hosts_line(host_line) if host_line else None,
        public_key_available=pub is not None,
    )
