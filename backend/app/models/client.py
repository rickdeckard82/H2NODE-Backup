from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Client(Base, TimestampMixin):
    """Origem de backups: servidor Linux (agente no crontab do root) ou
    equipamento de rede (switch/roteador que envia a configuração por FTP/TFTP)."""

    __tablename__ = "client"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Identificador do cliente no agente e nome da pasta em incoming/ e store/.
    slug: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # "server" (agente Linux) | "network" (equipamento que envia por FTP/TFTP)
    kind: Mapped[str] = mapped_column(String(16), default="server", server_default="server", index=True)

    # ---- Só para equipamentos de rede ----
    # datacom | huawei | juniper | fiberhome | mikrotik | generic — define as instruções e a validação.
    vendor: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # IP de origem com que o equipamento chega ao servidor (identifica o upload).
    # MikroTik (ssh): o IP onde o coletor conecta.
    mgmt_ip: Mapped[str | None] = mapped_column(String(45), nullable=True, unique=True)
    # ftp | tftp (o equipamento envia) | ssh (o coletor busca: MikroTik)
    protocol: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Só OLT Fiberhome: IP da UNM2000 que gerencia o FTP (apaga/renomeia o arquivo que a OLT
    # enviou). Esse IP também pode usar o FTP, em modo de compatibilidade (ver receivers/ftp.py).
    manager_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # ---- Só para equipamentos coletados por SSH (MikroTik) ----
    pull_credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("device_credential.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Porta SSH; vazio = a da credencial.
    pull_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Chave de host SSH fixada na 1ª conexão ("<tipo> <base64>"). Se mudar, a coleta
    # para até alguém aceitar a nova chave no painel.
    pull_host_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Próxima coleta (vazio = já). "Coletar agora" no painel zera.
    pull_next_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pull_last_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pull_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Chave pública SSH do agente. Vira uma linha do authorized_keys do container
    # sshd, presa (rrsync -wo) à pasta incoming/<slug>/.
    ssh_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_key_fingerprint: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Token do envio por HTTPS (cliente Windows). Só o SHA-256 fica no banco; o token
    # aparece uma única vez, ao ser gerado. `hint` = final do token, para reconhecê-lo.
    upload_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    upload_token_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Agenda esperada (o crontab do cliente) — base do alerta de backup atrasado.
    # 0 = sob demanda (ex.: Juniper transfer-on-commit): nunca acusa atraso.
    expected_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    # Retenção: apaga backups mais velhos que retention_days, mas nunca deixa
    # menos que retention_min_keep backups válidos.
    retention_days: Mapped[int] = mapped_column(Integer, default=30)
    retention_min_keep: Mapped[int] = mapped_column(Integer, default=7)

    # Informações reportadas pelo agente no último manifesto.
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    os_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    last_backup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    stored_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
