from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkerStatus(Base):
    """Linha única (id=1) atualizada pelo worker — o painel e o monitoramento mostram se ele
    está vivo, o que está fazendo e se a verificação profunda (chave privada) está ativa.

    `last_seen_at` vem de uma thread a cada HEARTBEAT_SECONDS, também durante tarefas longas
    (verificar um backup de centenas de GB leva horas): sem sinal = processo morto/travado.
    `busy_with`/`busy_since` = a tarefa atual (None = ocioso): tarefa velha = worker preso."""

    __tablename__ = "worker_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    deep_verify: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    busy_with: Mapped[str | None] = mapped_column(String(255), nullable=True)
    busy_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
