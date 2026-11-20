from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DeviceCredential(Base, TimestampMixin):
    """Usuário com que o coletor (serviço `puller`) entra por SSH nos equipamentos
    que o H2NODE Backup busca ativamente (hoje: MikroTik RouterOS).

    A senha é guardada cifrada (Fernet, FERNET_KEY) porque precisa ser usada — não
    dá para guardar só o hash. Ela nunca volta pela API.
    """

    __tablename__ = "device_credential"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64))
    password_enc: Mapped[str] = mapped_column(String(512))
    # Porta SSH padrão dos equipamentos que usam esta credencial (o host pode trocar).
    port: Mapped[int] = mapped_column(Integer, default=22)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
