from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.system_user import SystemRole
from app.schemas.common import UtcDatetime

_USERNAME = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")


class SystemUserCreate(BaseModel):
    username: str = _USERNAME
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=190)
    role: SystemRole = SystemRole.operator
    is_active: bool = True
    timezone: str = Field(default="America/Sao_Paulo", max_length=64)
    password: str = Field(min_length=10, max_length=128)


class SystemUserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=190)
    role: SystemRole | None = None
    is_active: bool | None = None
    timezone: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, min_length=10, max_length=128)


class SystemUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    full_name: str
    role: SystemRole
    is_active: bool
    timezone: str
    mfa_enabled: bool
    last_login_at: UtcDatetime | None
    created_at: UtcDatetime
