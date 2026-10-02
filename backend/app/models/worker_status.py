from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkerStatus(Base):
    """Linha única (id=1) atualizada pelo worker a cada ciclo — o painel mostra
    se ele está vivo e se a verificação profunda (chave privada) está ativa."""

    __tablename__ = "worker_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    deep_verify: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str | None] = mapped_column(String(255), nullable=True)
