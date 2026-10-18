from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

_NAME = Field(min_length=1, max_length=80)
_USER = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
# A senha vai entre aspas nos comandos do RouterOS: sem espaço, aspas, \, $ (variável)
# nem ? (abre a ajuda quando colado no terminal).
_PASSWORD = r'^[^\s"\\$?]+$'


class DeviceCredentialCreate(BaseModel):
    name: str = _NAME
    username: str = _USER
    password: str = Field(min_length=8, max_length=64, pattern=_PASSWORD)
    port: int = Field(default=22, ge=1, le=65535)
    description: str | None = Field(default=None, max_length=255)


class DeviceCredentialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    username: str | None = Field(default=None, min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    # ausente/vazio = mantém a senha atual
    password: str | None = Field(default=None, min_length=8, max_length=64, pattern=_PASSWORD)
    port: int | None = Field(default=None, ge=1, le=65535)
    description: str | None = Field(default=None, max_length=255)


class DeviceCredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    username: str
    port: int
    description: str | None
    # equipamentos que usam a credencial
    device_count: int = 0
    created_at: UtcDatetime
    updated_at: UtcDatetime
