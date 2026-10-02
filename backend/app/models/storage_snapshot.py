from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StorageSnapshot(Base):
    """Foto periódica do disco de backups (gráfico de crescimento do painel)."""

    __tablename__ = "storage_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    total_bytes: Mapped[int] = mapped_column(BigInteger)
    used_bytes: Mapped[int] = mapped_column(BigInteger)
    free_bytes: Mapped[int] = mapped_column(BigInteger)
    backups_bytes: Mapped[int] = mapped_column(BigInteger)
