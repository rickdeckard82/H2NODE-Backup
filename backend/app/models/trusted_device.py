from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TrustedDevice(Base):
    """Navegador lembrado no 2FA ("lembrar este dispositivo"): dispensa SÓ o código 2FA
    (a senha continua obrigatória) até `expires_at`. O cookie leva um token aleatório; aqui
    fica só o SHA-256 dele."""

    __tablename__ = "app_trusted_device"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_user_id: Mapped[int] = mapped_column(
        ForeignKey("app_system_user.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
