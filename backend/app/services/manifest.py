"""Manifesto enviado pelo agente (manifest.json, sempre o ÚLTIMO arquivo do upload).

É entrada não confiável: só o cliente dono da pasta consegue escrevê-la (chave
SSH presa à pasta), mas tudo é validado e limitado mesmo assim.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MANIFEST_NAME = "manifest.json"
MANIFEST_MAX_BYTES = 1024 * 1024
FORMAT = "h2node-backup/1"
# Agentes e clientes Windows anteriores ao rebranding (Pulse Backup) mandam
# "pulse-backup/1". O conteúdo é idêntico: continue aceitando até todos atualizarem.
LEGACY_FORMATS = ("pulse-backup/1",)

_SHA256 = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def _naive_utc(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    if v.tzinfo is not None:
        v = v.astimezone(UTC).replace(tzinfo=None)
    return v


class ManifestComponent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["files", "file", "mysql", "postgresql", "mssql"]
    name: str = Field(max_length=255)
    file: str | None = Field(default=None, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*\.gpg$")
    size: int = Field(default=0, ge=0)
    sha256: str | None = _SHA256
    plain_size: int = Field(default=0, ge=0)
    plain_sha256: str | None = _SHA256
    status: Literal["ok", "warning", "failed"]
    message: str | None = Field(default=None, max_length=4000)
    duration_s: int | None = Field(default=None, ge=0)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format: Literal["h2node-backup/1", "pulse-backup/1"]
    client_id: str = Field(max_length=48)
    run_name: str = Field(max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    agent_version: str | None = Field(default=None, max_length=32)
    hostname: str | None = Field(default=None, max_length=255)
    os: str | None = Field(default=None, max_length=255)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: Literal["success", "partial", "failed"]
    encryption_fingerprint: str | None = Field(default=None, max_length=64)
    components: list[ManifestComponent] = Field(default_factory=list, max_length=500)
    errors: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("started_at", "finished_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return _naive_utc(v)

    @field_validator("errors")
    @classmethod
    def _trim_errors(cls, v: list[str]) -> list[str]:
        return [e[:2000] for e in v]
