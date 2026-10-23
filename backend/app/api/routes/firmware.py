"""Página FTP Firmwares: arquivos que os equipamentos baixam por FTP/TFTP e quem pode baixar."""

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, enforce_csrf, require_admin, require_auditor
from app.core.config import settings
from app.core.db import get_db
from app.core.security import hash_password
from app.models import FirmwareNote, FirmwareSettings, FtpAccount, SystemUser
from app.schemas.common import UtcDatetime
from app.services import audit, firmware, receivers, storage

router = APIRouter(prefix="/firmware", tags=["firmware"])


class FirmwareFileOut(BaseModel):
    name: str
    comment: str | None = None
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


class ConnectionOut(BaseModel):
    id: str
    protocol: str
    ip: str
    user: str | None
    since: UtcDatetime
    file: str | None
    sent: int
    size: int | None


class ReceiverOut(BaseModel):
    online: bool
    updated_at: UtcDatetime | None


class ConnectionsOut(BaseModel):
    receivers: dict[str, ReceiverOut]
    connections: list[ConnectionOut]


def _settings_out(row: FirmwareSettings | None) -> FirmwareSettingsOut:
    if row is None:
        return FirmwareSettingsOut(enabled=False, ftp_username=None, has_password=False,
                                   allowed_networks=[], include_devices=True)
    return FirmwareSettingsOut(enabled=row.enabled, ftp_username=row.ftp_username,
                               has_password=bool(row.ftp_password_hash),
                               allowed_networks=firmware.networks_of(row),
                               include_devices=row.include_devices)


class CommentIn(BaseModel):
    comment: str = Field(default="", max_length=200)


def _notes(db: Session) -> dict[str, str]:
    return {n.name: n.comment for n in db.execute(select(FirmwareNote)).scalars()}


def _files_out(db: Session) -> list[FirmwareFileOut]:
    notes = _notes(db)
    return [FirmwareFileOut(**vars(f), comment=notes.get(f.name)) for f in firmware.list_files()]


def _file_out(db: Session, name: str) -> FirmwareFileOut:
    return next(f for f in _files_out(db) if f.name == name)


@router.get("", response_model=FirmwareOut)
def get_firmware(db: Session = Depends(get_db), _: SystemUser = Depends(require_auditor)) -> FirmwareOut:
    return FirmwareOut(
        files=_files_out(db),
        settings=_settings_out(db.get(FirmwareSettings, 1)),
        host=settings.net_host, ftp_port=settings.ftp_port, ftp_passive_ports=settings.ftp_passive_ports,
        tftp_port=settings.tftp_port,
        max_mb=settings.firmware_max_mb,
    )


@router.get("/connections", response_model=ConnectionsOut)
def connections(_: SystemUser = Depends(require_auditor)) -> ConnectionsOut:
    """Sessões de firmware abertas agora (FTP logado, TFTP transferindo), lidas do retrato
    que cada receptor publica em firmware/.status/."""
    recv: dict[str, ReceiverOut] = {}
    conns: list[ConnectionOut] = []
    for proto in ("ftp", "tftp"):
        online, at, sessions = firmware.read_status(proto)
        recv[proto] = ReceiverOut(online=online, updated_at=at)
        for s in sessions:
            try:
                conns.append(ConnectionOut(
                    id=str(s["id"]), protocol=proto, ip=str(s["ip"]), user=s.get("user"),
                    since=datetime.fromtimestamp(float(s["since"]), UTC).replace(tzinfo=None),
                    file=s.get("file"), sent=int(s.get("sent") or 0), size=s.get("size"),
                ))
            except (KeyError, TypeError, ValueError):
                continue
    return ConnectionsOut(receivers=recv, connections=sorted(conns, key=lambda c: c.since))


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
    return _file_out(db, name)


@router.put("/files/{name}/comment", response_model=FirmwareFileOut, dependencies=[Depends(enforce_csrf)])
def set_comment(name: str, body: CommentIn, request: Request, db: Session = Depends(get_db),
                actor: SystemUser = Depends(require_admin)) -> FirmwareFileOut:
    """Comentário curto do firmware (vazio apaga)."""
    if not firmware.NAME_RE.match(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "arquivo não encontrado")
    p = storage.safe_child(firmware.files_dir(), name)
    if p.is_symlink() or not p.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "arquivo não encontrado")
    text = " ".join(body.comment.split())  # uma linha, sem espaços sobrando
    note = db.get(FirmwareNote, name)
    before = note.comment if note else None
    if not text:
        if note:
            db.delete(note)
    elif note:
        note.comment = text
    else:
        db.add(FirmwareNote(name=name, comment=text))
    audit.record(db, action="update", entity_type="firmware", entity_id=name,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 before={"comment": before}, after={"comment": text or None})
    db.commit()
    return _file_out(db, name)


@router.delete("/files/{name}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(enforce_csrf)])
def delete_file(name: str, request: Request, db: Session = Depends(get_db),
                actor: SystemUser = Depends(require_admin)) -> None:
    if not firmware.NAME_RE.match(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "arquivo não encontrado")
    p = storage.safe_child(firmware.files_dir(), name)
    if p.is_symlink() or not p.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "arquivo não encontrado")
    p.unlink()
    note = db.get(FirmwareNote, name)
    if note:
        db.delete(note)
    audit.record(db, action="delete", entity_type="firmware", entity_id=name,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request))
    db.commit()
