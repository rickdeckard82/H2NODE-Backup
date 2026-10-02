from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import UtcDatetime

_USER = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")


class FtpAccountCreate(BaseModel):
    username: str = _USER
    # Equipamentos guardam a senha (às vezes com limite de tamanho/caracteres):
    # mínimo 8, sem espaços nem caracteres que quebram URL (@ : /).
    password: str = Field(min_length=8, max_length=64, pattern=r"^[^\s@:/]+$")
    description: str | None = Field(default=None, max_length=255)
    is_active: bool = True


class FtpAccountUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[^\s@:/]+$")
    description: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class FtpAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    description: str | None
    is_active: bool
    last_used_at: UtcDatetime | None
    created_at: UtcDatetime
