from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MonitoringSettings(Base, TimestampMixin):
    """Integração de monitoramento (Zabbix), linha única id=1.

    O Zabbix consulta GET /api/monitoring/status com `Authorization: Bearer <token>`. O token é
    gerado no painel e mostrado uma vez; aqui fica só o SHA-256. Sem token, o endpoint não existe
    (404). `allowed_networks` (CIDR, um por linha) restringe a origem; vazio = qualquer IP.
    """

    __tablename__ = "monitoring_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    allowed_networks: Mapped[str] = mapped_column(Text, default="")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
