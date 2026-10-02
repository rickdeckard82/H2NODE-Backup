import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")


class BackupStatus(str, enum.Enum):
    ok = "ok"                # tudo certo no cliente e na recepção
    warning = "warning"      # concluído com avisos (ex.: arquivo mudou durante o tar)
    failed = "failed"        # o agente (ou parte dele) falhou
    corrupted = "corrupted"  # tamanho/hash não confere com o manifesto


class VerifyStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    ok = "ok"
    failed = "failed"
    skipped = "skipped"      # nada a verificar (ex.: execução sem arquivos)


class Backup(Base):
    """Uma execução do agente num cliente (um diretório em store/<cliente>/)."""

    __tablename__ = "backup"
    __table_args__ = (UniqueConstraint("client_id", "run_name", name="uq_backup_client_run"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("client.id", ondelete="CASCADE"), index=True
    )
    run_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[BackupStatus] = mapped_column(
        Enum(BackupStatus, native_enum=False, length=16), index=True
    )
    agent_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    # Tamanho cifrado (o que ocupa no disco do servidor).
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    plain_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    # Caminho relativo a STORAGE_PATH. NULL => arquivos não guardados.
    storage_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)

    verify_status: Mapped[VerifyStatus] = mapped_column(
        Enum(VerifyStatus, native_enum=False, length=16), default=VerifyStatus.pending, index=True
    )
    # "full" (decifrou e testou o conteúdo) | "integrity" (hash + destinatário GPG)
    verify_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verify_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Removido pela retenção (ou manualmente). A linha fica para o histórico.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    components: Mapped[list["BackupComponent"]] = relationship(
        back_populates="backup",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BackupComponent.position",
    )
    client: Mapped["Client"] = relationship(lazy="joined")  # noqa: F821


class BackupComponent(Base):
    """Uma parte do backup: uma pasta (tar.gz) ou um banco (dump .sql.gz / .bak.gz)."""

    __tablename__ = "backup_component"

    id: Mapped[int] = mapped_column(primary_key=True)
    backup_id: Mapped[int] = mapped_column(
        ForeignKey("backup.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16))  # files | mysql | postgresql | mssql
    name: Mapped[str] = mapped_column(String(255))
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plain_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    plain_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # ok | warning | failed
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verify_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verify_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nº de entradas no tar (pastas), conferido na verificação profunda.
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    backup: Mapped[Backup] = relationship(back_populates="components")
