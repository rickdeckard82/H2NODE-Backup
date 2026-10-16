from pydantic import BaseModel, ConfigDict

from app.models.backup import BackupStatus, VerifyStatus
from app.schemas.common import UtcDatetime


class BackupComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    position: int
    kind: str
    name: str
    file_name: str | None
    size_bytes: int
    sha256: str | None
    plain_size_bytes: int
    plain_sha256: str | None
    status: str
    message: str | None
    duration_seconds: int | None
    verify_status: str | None
    verify_message: str | None
    item_count: int | None


class BackupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: int
    client_slug: str
    client_name: str
    run_name: str
    status: BackupStatus
    agent_status: str | None
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    received_at: UtcDatetime
    size_bytes: int
    plain_size_bytes: int
    error_message: str | None
    agent_version: str | None
    verify_status: VerifyStatus
    verify_mode: str | None
    verified_at: UtcDatetime | None
    verify_message: str | None
    deleted_at: UtcDatetime | None
    component_count: int = 0


class BackupDetailOut(BackupOut):
    components: list[BackupComponentOut]
    errors: list[str] = []
    hostname: str | None = None


class AccountOut(BaseModel):
    """Um arquivo/conta (ex.: backup de conta do cPanel) com a cópia mais recente e o nº de versões."""

    client_id: int
    client_name: str
    name: str
    versions: int
    last_backup_id: int
    last_component_id: int
    last_received_at: UtcDatetime
    size_bytes: int
    status: str
    verify_status: str | None
    file_name: str | None


class AccountVersionOut(BaseModel):
    backup_id: int
    component_id: int
    run_name: str
    received_at: UtcDatetime
    size_bytes: int
    status: str
    verify_status: str | None
    verify_message: str | None
    file_name: str | None
