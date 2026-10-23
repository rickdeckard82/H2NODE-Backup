from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FirmwareNote(Base, TimestampMixin):
    """Dados de um firmware (página FTP Firmwares) pelo nome do arquivo em
    STORAGE_PATH/firmware/files: comentário curto e fabricante. Ficam no banco: o arquivo
    servido não é tocado. Sem comentário nem fabricante, a linha é apagada."""

    __tablename__ = "firmware_note"

    name: Mapped[str] = mapped_column(String(201), primary_key=True)
    comment: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # mesmos valores do "Tipo" dos equipamentos (Client.vendor), sem "files"
    vendor: Mapped[str | None] = mapped_column(String(16), nullable=True)
