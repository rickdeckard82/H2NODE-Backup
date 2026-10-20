import ipaddress
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import UtcDatetime

# Mesmo formato aceito pelo agente (CLIENT_ID) — vira nome de pasta.
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$"


Kind = Literal["server", "network"]
Vendor = Literal["datacom", "huawei", "juniper", "fiberhome", "mikrotik", "generic", "files"]
# ssh = o coletor busca (MikroTik); ftp/tftp = o equipamento envia
Protocol = Literal["ftp", "tftp", "ssh"]


def _norm_ip(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    try:
        return str(ipaddress.ip_address(v.strip()))
    except ValueError as exc:
        raise ValueError("IP inválido") from exc


class ClientBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    kind: Kind = "server"
    vendor: Vendor | None = None
    mgmt_ip: str | None = Field(default=None, max_length=45)
    manager_ip: str | None = Field(default=None, max_length=45)
    protocol: Protocol | None = None
    # MikroTik: credencial de acesso SSH e porta (vazio = a da credencial)
    pull_credential_id: int | None = None
    pull_port: int | None = Field(default=None, ge=1, le=65535)
    ssh_public_key: str | None = Field(default=None, max_length=16384)
    # 0 = sob demanda (sem alerta de atraso)
    expected_interval_hours: int = Field(default=24, ge=0, le=24 * 31)

    @field_validator("mgmt_ip", "manager_ip")
    @classmethod
    def _ip(cls, v: str | None) -> str | None:
        return _norm_ip(v)
    retention_days: int = Field(default=30, ge=1, le=3650)
    retention_min_keep: int = Field(default=7, ge=1, le=1000)


class ClientCreate(ClientBase):
    slug: str = Field(pattern=SLUG_PATTERN)


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    vendor: Vendor | None = None
    mgmt_ip: str | None = Field(default=None, max_length=45)
    # enviado (inclusive vazio) = grava; ausente = mantém (por isso usa model_fields_set)
    manager_ip: str | None = Field(default=None, max_length=45)
    protocol: Protocol | None = None
    pull_credential_id: int | None = None
    # enviado (inclusive null) = grava; ausente = mantém
    pull_port: int | None = Field(default=None, ge=1, le=65535)
    # "" remove a chave (o cliente deixa de conseguir enviar).
    ssh_public_key: str | None = Field(default=None, max_length=16384)
    expected_interval_hours: int | None = Field(default=None, ge=0, le=24 * 31)

    @field_validator("mgmt_ip", "manager_ip")
    @classmethod
    def _ip(cls, v: str | None) -> str | None:
        return _norm_ip(v)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    retention_min_keep: int | None = Field(default=None, ge=1, le=1000)


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: str | None
    is_active: bool
    kind: str
    vendor: str | None
    mgmt_ip: str | None
    manager_ip: str | None
    protocol: str | None
    pull_credential_id: int | None
    pull_port: int | None
    pull_host_key_fingerprint: str | None = None
    pull_next_at: UtcDatetime | None
    pull_last_at: UtcDatetime | None
    pull_error: str | None
    ssh_public_key: str | None
    ssh_key_fingerprint: str | None
    # final do token de envio HTTPS (cliente Windows); null = sem token
    upload_token_hint: str | None
    expected_interval_hours: int
    retention_days: int
    retention_min_keep: int
    hostname: str | None
    os_info: str | None
    agent_version: str | None
    last_backup_at: UtcDatetime | None
    last_status: str | None
    stored_bytes: int
    backup_count: int = 0
    # ok | warning | failed | overdue | never | inactive — calculado na leitura.
    health: str = "never"
    created_at: UtcDatetime
    updated_at: UtcDatetime


class UploadTokenOut(BaseModel):
    """Token de envio por HTTPS. `token` só existe nesta resposta (não é guardado em claro)."""

    token: str
    hint: str
    server_url: str
    public_key_fingerprint: str | None


class AgentConfigOut(BaseModel):
    filename: str
    content: str
    known_hosts: str | None
    public_key_available: bool


class DeviceConfigOut(BaseModel):
    vendor: str
    protocol: str
    server_host: str
    ftp_user: str | None
    ftp_accounts: list[str]
    commands: str
    notes: list[str]
