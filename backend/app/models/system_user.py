import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.mfa_recovery_code import MfaRecoveryCode


class SystemRole(str, enum.Enum):
    admin = "admin"        # tudo: usuários do painel, auditoria, baixar/excluir backups
    operator = "operator"  # cadastra/edita clientes, pede reverificação
    auditor = "auditor"    # só leitura (painel, clientes, backups)


class SystemUser(Base, TimestampMixin):
    __tablename__ = "app_system_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(190), unique=True)
    full_name: Mapped[str] = mapped_column(String(190))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[SystemRole] = mapped_column(
        Enum(SystemRole, native_enum=False, length=20), default=SystemRole.operator
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Fuso IANA para exibir datas e agrupar os gráficos por dia (só na apresentação).
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    # Fernet. NULL => 2FA não configurado. `mfa_enabled=False` com secret != NULL
    # é um setup pendente de confirmação (ver /auth/mfa/enable).
    mfa_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Nº de bloqueios consecutivos já aplicados — cresce a duração do próximo
    # (backoff exponencial); zera no primeiro login bem-sucedido.
    lockout_strikes: Mapped[int] = mapped_column(Integer, default=0)

    mfa_recovery_codes: Mapped[list[MfaRecoveryCode]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def mfa_recovery_codes_remaining(self) -> int:
        return sum(1 for c in self.mfa_recovery_codes if c.used_at is None)
