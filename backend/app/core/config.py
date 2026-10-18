import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Variáveis que aceitam a convenção <NOME>_FILE (Docker secrets). Se o arquivo
# existir e a variável direta não estiver definida, o conteúdo do arquivo é usado.
_FILE_BACKED = (
    "JWT_SECRET",
    "FERNET_KEY",
    "DATABASE_URL",
    "BOOTSTRAP_ADMIN_PASSWORD",
    "BACKUP_KEY_PASSPHRASE",
)


def _load_file_secrets() -> None:
    for name in _FILE_BACKED:
        path = os.environ.get(f"{name}_FILE")
        if path and not os.environ.get(name):
            p = Path(path)
            if p.is_file():
                os.environ[name] = p.read_text(encoding="utf-8").strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Banco
    database_url: str = Field(
        default="postgresql+psycopg://pulse:pulse@db:5432/pulse_backup",
        alias="DATABASE_URL",
    )

    # Segurança
    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = Field(default=15, alias="ACCESS_TOKEN_TTL_MINUTES")
    refresh_token_ttl_days: int = Field(default=7, alias="REFRESH_TOKEN_TTL_DAYS")
    fernet_key: str = Field(alias="FERNET_KEY")

    # HTTP
    frontend_origin: str = Field(default="https://localhost", alias="FRONTEND_ORIGIN")
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")
    cookie_domain: str | None = Field(default=None, alias="COOKIE_DOMAIN")
    api_prefix: str = "/api"
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # Expor /api/docs e /api/openapi.json. Desligado por padrão (produção).
    enable_docs: bool = Field(default=False, alias="ENABLE_DOCS")

    # Bootstrap do primeiro admin (usado pelo seed)
    bootstrap_admin_username: str = Field(default="admin", alias="BOOTSTRAP_ADMIN_USERNAME")
    bootstrap_admin_email: str = Field(default="admin@example.com", alias="BOOTSTRAP_ADMIN_EMAIL")
    bootstrap_admin_password: str = Field(default="", alias="BOOTSTRAP_ADMIN_PASSWORD")

    # ---- Armazenamento dos backups ----
    # Pasta do host montada no container (BACKUP_STORAGE_PATH no compose). Dentro
    # dela: incoming/<cliente>/ (área de upload via rsync), store/<cliente>/
    # (backups aceitos) e quarantine/ (uploads rejeitados).
    storage_path: str = Field(default="/data", alias="STORAGE_PATH")
    # Volume compartilhado com o container sshd: authorized_keys gerado pelo
    # painel e a chave pública de host do SSH (exibida para o cliente fixar).
    ssh_shared_dir: str = Field(default="/ssh", alias="SSH_SHARED_DIR")
    # Endereço público do SSH/rsync informado na configuração do agente.
    ssh_public_host: str = Field(default="backup.example.com", alias="SSH_PUBLIC_HOST")
    ssh_public_port: int = Field(default=2222, alias="SSH_PUBLIC_PORT")
    # uid do usuário "backup" no container sshd (dono dos arquivos enviados).
    ssh_user: str = "backup"

    # ---- Receptores FTP/TFTP (equipamentos de rede) ----
    # Volume compartilhado com os containers ftp/tftp: lista de IPs autorizados e
    # contas FTP (hash), gerada pelo painel. Eles não acessam o banco.
    receivers_shared_dir: str = Field(default="/netcfg", alias="RECEIVERS_SHARED_DIR")
    # Endereço que os EQUIPAMENTOS usam para chegar aqui (vai nos comandos de
    # exemplo). Vazio = SSH_PUBLIC_HOST.
    net_public_host: str = Field(default="", alias="NET_PUBLIC_HOST")
    ftp_port: int = Field(default=21, alias="FTP_PORT")
    # Faixa de portas do modo passivo (libere no ufw para os IPs dos equipamentos).
    ftp_passive_ports: str = Field(default="30000-30049", alias="FTP_PASSIVE_PORTS")
    # IP anunciado no PASV quando o servidor está atrás de NAT. Vazio = o da interface.
    ftp_masquerade_address: str | None = Field(default=None, alias="FTP_MASQUERADE_ADDRESS")
    tftp_port: int = Field(default=69, alias="TFTP_PORT")
    # Tamanho máximo de um arquivo de configuração recebido.
    net_max_file_mb: int = Field(default=64, alias="NET_MAX_FILE_MB")

    # ---- Coletor (puller): MikroTik por SSH ----
    # Coletas simultâneas e tempo máximo sem resposta do equipamento.
    pull_concurrency: int = Field(default=4, ge=1, le=32, alias="PULL_CONCURRENCY")
    pull_timeout_seconds: int = Field(default=60, ge=5, le=600, alias="PULL_TIMEOUT_SECONDS")

    # ---- Chave GPG dos backups ----
    # Pública: distribuída aos clientes (cifram para ela). Privada: só no worker,
    # para a verificação profunda (decifrar e testar o conteúdo). Sem a privada o
    # sistema roda em modo "integridade" (hash + destinatário correto).
    backup_public_key_path: str = Field(
        default="/keys/backup-key.pub.asc", alias="BACKUP_PUBLIC_KEY_PATH"
    )
    backup_private_key_path: str | None = Field(default=None, alias="BACKUP_PRIVATE_KEY_PATH")
    backup_key_passphrase: str | None = Field(default=None, alias="BACKUP_KEY_PASSPHRASE")

    # ---- Worker ----
    worker_poll_seconds: int = Field(default=30, alias="WORKER_POLL_SECONDS")
    # Upload sem manifesto há mais que isso => incompleto, vai para quarentena.
    incoming_stale_hours: int = Field(default=12, alias="INCOMING_STALE_HOURS")
    # Reverificação periódica dos backups guardados (detecta corrupção no disco).
    # 0 desliga.
    reverify_interval_days: int = Field(default=30, alias="REVERIFY_INTERVAL_DAYS")
    storage_snapshot_minutes: int = Field(default=60, alias="STORAGE_SNAPSHOT_MINUTES")
    # Margem além do intervalo esperado antes de marcar o cliente como atrasado.
    overdue_grace_minutes: int = Field(default=120, alias="OVERDUE_GRACE_MINUTES")

    @property
    def net_host(self) -> str:
        return self.net_public_host or self.ssh_public_host

    @property
    def passive_port_range(self) -> tuple[int, int]:
        a, _, b = self.ftp_passive_ports.partition("-")
        return int(a), int(b or a)

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_strength(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET deve ter no mínimo 32 caracteres (use: openssl rand -hex 32)")
        return v

    @property
    def access_cookie_name(self) -> str:
        return "pb_access"

    @property
    def refresh_cookie_name(self) -> str:
        return "pb_refresh"

    @property
    def csrf_cookie_name(self) -> str:
        return "pb_csrf"


@lru_cache
def get_settings() -> Settings:
    _load_file_secrets()
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
