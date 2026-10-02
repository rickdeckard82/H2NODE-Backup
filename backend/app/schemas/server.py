from pydantic import BaseModel


class ServerInfoOut(BaseModel):
    public_key_available: bool
    public_key_fingerprint: str | None
    public_key_uid: str | None
    deep_verify_enabled: bool
    ssh_host: str
    ssh_port: int
    ssh_host_key: str | None
    ssh_host_key_fingerprint: str | None
    storage_path: str
    disk_total_bytes: int
    disk_used_bytes: int
    disk_free_bytes: int
