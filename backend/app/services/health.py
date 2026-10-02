"""Saúde de um cliente, calculada na leitura (sem estado próprio)."""

from datetime import timedelta

from app.core.config import settings
from app.core.security import utcnow
from app.models import Client


def client_health(c: Client) -> str:
    """ok | warning | failed | overdue | never | inactive"""
    if not c.is_active:
        return "inactive"
    if c.last_backup_at is None:
        return "never"
    # intervalo 0 = sob demanda (ex.: envio a cada commit): nunca "atrasado"
    if c.expected_interval_hours > 0:
        limit = timedelta(hours=c.expected_interval_hours, minutes=settings.overdue_grace_minutes)
        if utcnow() - c.last_backup_at > limit:
            return "overdue"
    if c.last_status in ("failed", "corrupted"):
        return "failed"
    if c.last_status == "warning":
        return "warning"
    return "ok"
