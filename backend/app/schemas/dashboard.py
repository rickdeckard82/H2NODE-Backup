from pydantic import BaseModel

from app.schemas.common import UtcDatetime


class DailyPoint(BaseModel):
    date: str  # YYYY-MM-DD no fuso do usuário
    ok: int = 0
    warning: int = 0
    failed: int = 0
    bytes: int = 0


class StoragePoint(BaseModel):
    date: str
    used_bytes: int
    free_bytes: int
    backups_bytes: int


class ClientSize(BaseModel):
    id: int
    name: str
    slug: str
    stored_bytes: int


class RecentProblem(BaseModel):
    id: int
    client_name: str
    received_at: UtcDatetime
    status: str
    verify_status: str
    message: str | None


class OverdueClient(BaseModel):
    id: int
    name: str
    slug: str
    health: str
    last_backup_at: UtcDatetime | None
    expected_interval_hours: int


class WorkerInfo(BaseModel):
    online: bool
    last_seen_at: UtcDatetime | None
    deep_verify: bool
    message: str | None


class DashboardOut(BaseModel):
    days: int
    clients_total: int
    clients_active: int
    servers_active: int = 0
    devices_active: int = 0
    clients_health: dict[str, int]
    last24h: dict[str, int]
    window: dict[str, int]
    success_rate: float | None
    bytes_window: int
    daily: list[DailyPoint]
    verification: dict[str, int]
    disk_total_bytes: int
    disk_used_bytes: int
    disk_free_bytes: int
    backups_bytes: int
    storage_history: list[StoragePoint]
    top_clients: list[ClientSize]
    recent_problems: list[RecentProblem]
    overdue_clients: list[OverdueClient]
    worker: WorkerInfo
