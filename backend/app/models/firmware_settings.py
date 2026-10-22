from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FirmwareSettings(Base, TimestampMixin):
    """Servidor de firmwares (linha única, id=1): quem pode BAIXAR os arquivos de
    STORAGE_PATH/firmware/files por FTP/TFTP.

    É a única área que os receptores servem para leitura — os backups continuam só
    gravação. Acesso: IPs das redes liberadas e, se `include_devices`, dos equipamentos
    de rede ativos. FTP pede o login abaixo (senha em hash Argon2id); TFTP não tem login.
    """

    __tablename__ = "firmware_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ftp_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ftp_password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # redes/IPs liberados, um por linha (CIDR)
    allowed_networks: Mapped[str] = mapped_column(Text, default="")
    include_devices: Mapped[bool] = mapped_column(Boolean, default=True)
