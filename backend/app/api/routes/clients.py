from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, enforce_csrf, require_admin, require_auditor, require_operator
from app.core.config import settings
from app.core.db import get_db
from app.models import Backup, Client, FtpAccount, SystemUser
from app.schemas.client import AgentConfigOut, ClientCreate, ClientOut, ClientUpdate, DeviceConfigOut
from app.services import audit, gpg, receivers, sshkeys, storage
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


def _apply_network(db: Session, c: Client) -> None:
    """Coerência dos campos por tipo: equipamento de rede exige fabricante, IP
    de origem e protocolo (e não tem chave SSH); servidor não tem nenhum deles."""
    if c.kind == "network":
        if not (c.vendor and c.mgmt_ip and c.protocol):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "equipamento de rede precisa de fabricante, IP de origem e protocolo")
        c.ssh_public_key = None
        c.ssh_key_fingerprint = None
        if db.execute(select(Client.id).where(Client.mgmt_ip == c.mgmt_ip, Client.id != (c.id or 0))).first():
            # o upload é atribuído pelo IP de origem: precisa ser único
            raise HTTPException(status.HTTP_409_CONFLICT, f"o IP {c.mgmt_ip} já pertence a outro equipamento")
        if c.vendor != "fiberhome" or c.protocol != "ftp":
            c.manager_ip = None  # só OLT Fiberhome por FTP tem UNM2000
        if c.manager_ip:
            if c.manager_ip == c.mgmt_ip:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                    "o IP da UNM2000 não pode ser o da própria OLT")
            owner = db.execute(select(Client.name).where(Client.mgmt_ip == c.manager_ip)).scalar_one_or_none()
            if owner:
                # um IP não pode ser equipamento e gerenciador ao mesmo tempo
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"o IP {c.manager_ip} já está cadastrado como equipamento ('{owner}'): exclua esse "
                    "cadastro — o IP da UNM2000 é informado em cada OLT",
                )
        elif c.mgmt_ip and db.execute(
            select(Client.name).where(Client.manager_ip == c.mgmt_ip, Client.id != (c.id or 0))
        ).first():
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"o IP {c.mgmt_ip} já é usado como IP da UNM2000 em outra OLT")
    else:
        c.vendor = c.mgmt_ip = c.manager_ip = c.protocol = None


def _sync_all(db: Session) -> None:
    sshkeys.sync_authorized_keys(db)
    receivers.sync(db)


@router.get("", response_model=list[ClientOut])
def list_clients(
    db: Session = Depends(get_db),
    _: SystemUser = Depends(require_auditor),
    q: str | None = Query(None, max_length=100),
    kind: str | None = Query(None, pattern="^(server|network)$"),
) -> list[ClientOut]:
    stmt = select(Client)
    if kind:
        stmt = stmt.where(Client.kind == kind)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Client.name.ilike(like), Client.slug.ilike(like),
                              Client.hostname.ilike(like), Client.mgmt_ip.ilike(like)))
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
        kind=body.kind, vendor=body.vendor, mgmt_ip=body.mgmt_ip, manager_ip=body.manager_ip,
        protocol=body.protocol,
        expected_interval_hours=body.expected_interval_hours,
        retention_days=body.retention_days, retention_min_keep=body.retention_min_keep,
    )
    if c.kind == "server":
        _apply_key(c, body.ssh_public_key)
        _check_key_unique(db, c)
    _apply_network(db, c)
    db.add(c)
    db.flush()
    audit.record(db, action="create", entity_type="client", entity_id=c.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 after={"slug": c.slug, "name": c.name, "kind": c.kind, "ssh_key": c.ssh_key_fingerprint,
                        "mgmt_ip": c.mgmt_ip, "manager_ip": c.manager_ip, "protocol": c.protocol})
    db.commit()
    storage.ensure_client_dirs(c.slug)
    _sync_all(db)
    return _to_out(db, c)


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(
    client_id: int, body: ClientUpdate, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_operator),
) -> ClientOut:
    c = db.get(Client, client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "não encontrado")
    fields = ("name", "description", "is_active", "expected_interval_hours", "retention_days",
              "retention_min_keep", "vendor", "mgmt_ip", "protocol")
    before = {f: getattr(c, f) for f in (*fields, "manager_ip") if f != "description"} | {
        "ssh_key": c.ssh_key_fingerprint
    }
    for field in fields:
        v = getattr(body, field)
        if v is not None:
            setattr(c, field, v)
    if "manager_ip" in body.model_fields_set:
        c.manager_ip = body.manager_ip  # None/"" remove
    if c.kind == "server":
        _apply_key(c, body.ssh_public_key)
        _check_key_unique(db, c)
    _apply_network(db, c)
    audit.record(db, action="update", entity_type="client", entity_id=c.id,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 before=before,
                 after={f: getattr(c, f) for f in fields if f != "description"}
                 | {"ssh_key": c.ssh_key_fingerprint})
    db.commit()
    _sync_all(db)
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
                 before={"slug": c.slug, "name": c.name, "kind": c.kind})
    db.commit()
    _sync_all(db)


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

# ---- Arquivos como estão (ex.: backups de conta do cPanel) ----
# Cada arquivo é cifrado como está e enviado um a um (cifra, envia, apaga): a pasta
# WORK_DIR só precisa caber o MAIOR arquivo. "@latest" = a pasta datada mais recente.
BACKUP_FILES=(
  # "/backup/cpanel/@latest/accounts/*.tar.gz"
)

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
    if c.kind != "server":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "equipamento de rede não usa o agente — veja device-config")
    pub = gpg.public_key_info()
    host_line, _fp = sshkeys.host_key()
    return AgentConfigOut(
        filename="agent.conf",
        content=render_agent_config(c, pub.fingerprint if pub else None),
        known_hosts=sshkeys.known_hosts_line(host_line) if host_line else None,
        public_key_available=pub is not None,
    )


def render_device_commands(c: Client, host: str, ftp_user: str) -> tuple[str, list[str]]:
    """Comandos a colar no equipamento para ele enviar a configuração para cá."""
    notes: list[str] = []
    if c.vendor == "datacom" and c.protocol == "tftp":
        cmds = (
            "show running-config | save overwrite config.txt\n"
            f"copy file config.txt tftp://{host}/{c.slug}/ source {c.mgmt_ip}"
        )
        notes.append("O DmOS envia sob comando: agende os dois comandos na sua automação "
                     "(ou rode-os após cada alteração).")
    elif c.vendor == "huawei" and c.protocol == "ftp":
        cmds = (
            "system-view\n"
            "set save-configuration delay 1\n"
            f"set save-configuration backup-to-server server {host} transport-type ftp "
            f"user {ftp_user} password <SENHA-FTP> path ./{c.mgmt_ip}"
        )
        notes.append("O VRP envia a cada salvamento da configuração (sob demanda: use intervalo 0).")
    elif c.vendor == "juniper" and c.protocol == "ftp":
        cmds = (
            "configure\n"
            "set system archival configuration transfer-on-commit\n"
            f'set system archival configuration archive-sites "ftp://{ftp_user}:<SENHA-FTP>@{host}"\n'
            "commit"
        )
        notes.append("O Junos envia um .conf.gz a cada commit (sob demanda: use intervalo 0).")
    elif c.vendor == "fiberhome" and c.protocol == "ftp":
        cmds = (
            "# Na UNM2000: tarefa de exportação de configuração com destino FTP (cada OLT envia direto)\n"
            f"servidor FTP : {host}   (porta 21, modo passivo)\n"
            f"usuário      : {ftp_user}\n"
            "senha        : <SENHA-FTP>"
        )
        notes.append("Cada OLT envia o próprio arquivo direto ao servidor, a partir do IP dela: cadastre UM "
                     "equipamento por OLT (IP de origem = IP da OLT).")
        if c.manager_ip:
            notes.append(f"A UNM2000 ({c.manager_ip}) também pode usar o FTP: ela apaga/renomeia o arquivo "
                         "que a OLT enviou e o servidor responde sucesso sem alterar nada. Libere esse IP "
                         "no ufw (scripts/ufw-setup.sh device <IP> ftp).")
        else:
            notes.append("Informe o IP da UNM2000 no cadastro: sem ele a UNM2000 é recusada ao tentar "
                         "apagar/renomear o arquivo e acusa falha de conexão.")
        notes.append("O intervalo esperado segue a tarefa de exportação da UNM2000 (ex.: 24 h).")
    elif c.protocol == "tftp":
        cmds = f"# envie o arquivo de configuração por TFTP (modo octet) para\ntftp://{host}/{c.slug}/config.txt"
    else:
        cmds = f"# envie o arquivo de configuração por FTP\nftp://{ftp_user}:<SENHA-FTP>@{host}/"
    notes.append(f"O servidor só aceita o envio a partir do IP {c.mgmt_ip} (identifica o equipamento).")
    if c.protocol == "ftp":
        notes.append("Troque <SENHA-FTP> pela senha da conta FTP (Configuração → Contas FTP).")
    return cmds, notes


@router.get("/{client_id}/device-config", response_model=DeviceConfigOut)
def device_config(
    client_id: int, db: Session = Depends(get_db), _: SystemUser = Depends(require_operator),
    ftp_user: str | None = Query(None, max_length=64),
) -> DeviceConfigOut:
    c = db.get(Client, client_id)
    if c is None or c.kind != "network":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "equipamento não encontrado")
    accounts = [a.username for a in db.execute(
        select(FtpAccount).where(FtpAccount.is_active.is_(True)).order_by(FtpAccount.username)
    ).scalars()]
    user = ftp_user if ftp_user in accounts else (accounts[0] if accounts else None)
    cmds, notes = render_device_commands(c, settings.net_host, user or "<usuario-ftp>")
    if c.protocol == "ftp" and not accounts:
        notes.insert(0, "Nenhuma conta FTP ativa — crie uma em Configuração → Contas FTP.")
    return DeviceConfigOut(vendor=c.vendor or "generic", protocol=c.protocol or "",
                           server_host=settings.net_host, ftp_user=user, ftp_accounts=accounts,
                           commands=cmds, notes=notes)
