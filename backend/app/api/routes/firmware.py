"""Página FTP Firmwares: arquivos que os equipamentos baixam por FTP/TFTP e quem pode baixar."""

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, enforce_csrf, require_admin, require_auditor
from app.core.config import settings
from app.core.db import get_db
from app.core.security import hash_password
from app.models import FirmwareSettings, FtpAccount, SystemUser
from app.schemas.common import UtcDatetime
from app.services import audit, firmware, receivers, storage

router = APIRouter(prefix="/firmware", tags=["firmware"])


class FirmwareFileOut(BaseModel):
    name: str
    size: int
    sha256: str
    updated_at: UtcDatetime


class FirmwareSettingsOut(BaseModel):
    enabled: bool
    ftp_username: str | None
    has_password: bool
    allowed_networks: list[str]
    include_devices: bool


class FirmwareOut(BaseModel):
    files: list[FirmwareFileOut]
    settings: FirmwareSettingsOut
    host: str
    ftp_port: int
    ftp_passive_ports: str
    tftp_port: int
    max_mb: int


class FirmwareSettingsIn(BaseModel):
    enabled: bool
    ftp_username: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9._-]{2,64}$")
    # mesmas regras das Contas FTP: equipamentos guardam a senha e às vezes a põem numa URL
    ftp_password: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[^\s@:/]+$")
    allowed_networks: list[str] = Field(default_factory=list, max_length=200)
    include_devices: bool = True


def _settings_out(row: FirmwareSettings | None) -> FirmwareSettingsOut:
    if row is None:
        return FirmwareSettingsOut(enabled=False, ftp_username=None, has_password=False,
                                   allowed_networks=[], include_devices=True)
    return FirmwareSettingsOut(enabled=row.enabled, ftp_username=row.ftp_username,
                               has_password=bool(row.ftp_password_hash),
                               allowed_networks=firmware.networks_of(row),
                               include_devices=row.include_devices)


def _file_out(name: str) -> FirmwareFileOut:
    f = next(f for f in firmware.list_files() if f.name == name)
    return FirmwareFileOut(**vars(f))


@router.get("", response_model=FirmwareOut)
def get_firmware(db: Session = Depends(get_db), _: SystemUser = Depends(require_auditor)) -> FirmwareOut:
    return FirmwareOut(
        files=[FirmwareFileOut(**vars(f)) for f in firmware.list_files()],
        settings=_settings_out(db.get(FirmwareSettings, 1)),
        host=settings.net_host, ftp_port=settings.ftp_port, ftp_passive_ports=settings.ftp_passive_ports,
        tftp_port=settings.tftp_port,
        max_mb=settings.firmware_max_mb,
    )


@router.put("/settings", response_model=FirmwareSettingsOut, dependencies=[Depends(enforce_csrf)])
def update_settings(body: FirmwareSettingsIn, request: Request, db: Session = Depends(get_db),
                    actor: SystemUser = Depends(require_admin)) -> FirmwareSettingsOut:
    try:
        nets = firmware.parse_networks(body.allowed_networks)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    user = body.ftp_username or None
    if user and db.execute(select(FtpAccount.id).where(FtpAccount.username == user)).first():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "já existe uma Conta FTP (de backup) com este usuário — use outro nome")
    row = firmware.get_settings(db)
    # trocar o usuário sem senha nova manteria a senha antiga sem ninguém ver: pede a senha
    keep = row.ftp_password_hash if user == row.ftp_username else None
    if user and not (body.ftp_password or keep):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "informe a senha do usuário FTP")
    if not user:
        row.ftp_password_hash = None
    elif body.ftp_password:
        row.ftp_password_hash = hash_password(body.ftp_password)
    row.ftp_username = user
    row.enabled = body.enabled
    row.allowed_networks = "\n".join(nets)
    row.include_devices = body.include_devices
    audit.record(db, action="update", entity_type="firmware_settings", entity_id=1,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 after={"enabled": row.enabled, "ftp_username": user, "networks": nets,
                        "include_devices": row.include_devices, "password_changed": bool(body.ftp_password)})
    db.commit()
    firmware.ensure_layout()
    receivers.sync(db)
    return _settings_out(row)


@router.put("/files/{name}", response_model=FirmwareFileOut, dependencies=[Depends(enforce_csrf)])
async def upload_file(name: str, request: Request, actor: SystemUser = Depends(require_admin),
                      db: Session = Depends(get_db)) -> FirmwareFileOut:
    """Envia (ou substitui) um firmware. O nome é o que o equipamento vai pedir."""
    if not firmware.NAME_RE.match(name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "nome inválido: use letras, números, ponto, hífen e sublinhado (sem espaços), "
                            "começando por letra ou número")
    firmware.ensure_layout()
    dest = storage.safe_child(firmware.files_dir(), name)
    fd, tmp = tempfile.mkstemp(dir=firmware.tmp_dir(), prefix="upload-")
    size, limit = 0, firmware.max_bytes()
    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                                        f"arquivo maior que {settings.firmware_max_mb} MB (FIRMWARE_MAX_MB)")
                f.write(chunk)
        if size == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "arquivo vazio")
        os.chmod(tmp, 0o644)
        replaced = dest.exists()
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    audit.record(db, action="upload", entity_type="firmware", entity_id=name,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 after={"size": size, "replaced": replaced})
    db.commit()
    return _file_out(name)


@router.delete("/files/{name}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(enforce_csrf)])
def delete_file(name: str, request: Request, db: Session = Depends(get_db),
                actor: SystemUser = Depends(require_admin)) -> None:
    if not firmware.NAME_RE.match(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "arquivo não encontrado")
    p = storage.safe_child(firmware.files_dir(), name)
    if p.is_symlink() or not p.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "arquivo não encontrado")
    p.unlink()
    audit.record(db, action="delete", entity_type="firmware", entity_id=name,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request))
    db.commit()
