from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class MfaRecoveryCode(Base):
    """Código de recuperação do 2FA (uso único).

    Gerado em lote quando o usuário ativa o 2FA. Serve para entrar ou
    desativar o 2FA quando o dispositivo TOTP é perdido. Guardado apenas como
    hash Argon2 — o valor em claro é mostrado uma única vez na ativação.
    """

    __tablename__ = "app_mfa_recovery_code"

    id: Mapped[int] = mapped_column(primary_key=True)
    system_user_id: Mapped[int] = mapped_column(
        ForeignKey("app_system_user.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["SystemUser"] = relationship(back_populates="mfa_recovery_codes")  # noqa: F821
