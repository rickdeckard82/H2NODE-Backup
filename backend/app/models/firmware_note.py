from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FirmwareNote(Base, TimestampMixin):
    """Comentário curto de um firmware (página FTP Firmwares), pelo nome do arquivo em
    STORAGE_PATH/firmware/files. Fica no banco: o arquivo servido não é tocado."""

    __tablename__ = "firmware_note"

    name: Mapped[str] = mapped_column(String(201), primary_key=True)
    comment: Mapped[str] = mapped_column(String(200))
