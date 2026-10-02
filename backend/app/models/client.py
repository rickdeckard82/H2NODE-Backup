from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Client(Base, TimestampMixin):
    """Servidor Linux que envia backups (roda o agente via crontab do root)."""

    __tablename__ = "client"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Identificador do cliente no agente e nome da pasta em incoming/ e store/.
    slug: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Chave pública SSH do agente. Vira uma linha do authorized_keys do container
    # sshd, presa (rrsync -wo) à pasta incoming/<slug>/.
    ssh_public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_key_fingerprint: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Agenda esperada (o crontab do cliente) — base do alerta de backup atrasado.
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
