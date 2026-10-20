from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FtpAccount(Base, TimestampMixin):
    """Conta do receptor FTP usada pelos equipamentos (ex.: "juniper").

    Só funciona a partir do IP de um equipamento de rede ativo com protocolo
    FTP; o upload é atribuído ao equipamento pelo IP de origem (e, se o IP tiver mais de um
    cadastro FTP, pela conta presa a cada um — Client.ftp_account_id). A conta só grava
    (não lê, não apaga). Senha guardada como hash Argon2id.
    """

    __tablename__ = "ftp_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
