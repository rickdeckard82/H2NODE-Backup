import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import (
    client_ip,
    enforce_csrf,
    get_current_user,
    require_admin,
    require_mfa_ready,
    require_auditor,
    require_operator,
)
from app.core.config import settings
from app.core.db import get_db
from app.models import SystemUser
from app.schemas.common import UtcDatetime
from app.services import audit, downloads, storage

router = APIRouter(prefix="/downloads", tags=["downloads"])


class DownloadOut(BaseModel):
    name: str
    title: str
    platform: str
    source: str
    size: int
    sha256: str
    updated_at: UtcDatetime
    version: str | None


class DownloadsOut(BaseModel):
    items: list[DownloadOut]
    problems: list[str]


class LinkOut(BaseModel):
    url: str
    expires_at: UtcDatetime


@router.get("", response_model=DownloadsOut)
def list_downloads(_: SystemUser = Depends(require_auditor)) -> DownloadsOut:
    items, problems = downloads.list_items()
    return DownloadsOut(items=[DownloadOut(**vars(i)) for i in items], problems=problems)


@router.get("/file/{name}")
def download_file(
    name: str, request: Request, db: Session = Depends(get_db),
    t: str | None = Query(None, max_length=120),
) -> Response:
    """Com login (cookie do painel) ou com o link temporário (?t=…), para `curl` no servidor."""
    actor: SystemUser | None = None
    if t:
        if not downloads.check(name, t):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "link inválido ou expirado — gere outro no painel")
    else:
        actor = require_mfa_ready(get_current_user(request, db))
    found = downloads.open_item(name)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "arquivo não encontrado")
    content, ctype = found
    audit.record(db, action="download", entity_type="download", entity_id=name,
                 actor_id=actor.id if actor else None,
                 actor_username=actor.username if actor else "(link temporário)",
                 ip_address=client_ip(request))
    db.commit()
    if isinstance(content, Path):
        return FileResponse(content, media_type=ctype, filename=name)
    disposition = f'attachment; filename="{name}"'
    return Response(content, media_type=ctype, headers={"Content-Disposition": disposition})


@router.post("/{name}/link", response_model=LinkOut, dependencies=[Depends(enforce_csrf)])
def create_link(
    name: str, request: Request,
    db: Session = Depends(get_db), actor: SystemUser = Depends(require_operator),
) -> LinkOut:
    if downloads.open_item(name) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "arquivo não encontrado")
    token, exp = downloads.sign(name)
    audit.record(db, action="download_link", entity_type="download", entity_id=name,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request))
    db.commit()
    base = settings.frontend_origin.rstrip("/")
    return LinkOut(url=f"{base}{settings.api_prefix}/downloads/file/{name}?t={token}",
                   expires_at=datetime.fromtimestamp(exp, UTC).replace(tzinfo=None))


@router.put("/{name}", response_model=DownloadOut, dependencies=[Depends(enforce_csrf)])
async def upload(name: str, request: Request, actor: SystemUser = Depends(require_admin),
                 db: Session = Depends(get_db)) -> DownloadOut:
    """Envia (ou substitui) um arquivo para download — ex.: o instalador do Windows."""
    if not downloads.UPLOAD_RE.match(name) or name.startswith("pulse-backup-agent-"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "nome inválido: use letras, números, ponto, hífen e extensão .exe, .msi, .zip "
                            "ou .tar.gz (o agente Linux é gerado sozinho)")
    if name in downloads.built_names():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "este arquivo é compilado pelo próprio servidor (client-builder) — não precisa enviar")
    d = downloads.uploads_dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = storage.safe_child(d, name)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".upload-")
    size = 0
    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > downloads.UPLOAD_MAX:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "arquivo maior que 512 MB")
                f.write(chunk)
        if size == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "arquivo vazio")
        os.chmod(tmp, 0o644)
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    audit.record(db, action="upload", entity_type="download", entity_id=name,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request),
                 after={"size": size})
    db.commit()
    item = next(i for i in downloads.list_items()[0] if i.name == name)
    return DownloadOut(**vars(item))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(enforce_csrf)])
def delete_upload(name: str, request: Request, db: Session = Depends(get_db),
                  actor: SystemUser = Depends(require_admin)) -> None:
    if not downloads.UPLOAD_RE.match(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "só arquivos enviados podem ser excluídos")
    p = storage.safe_child(downloads.uploads_dir(), name)
    if not p.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "arquivo não encontrado")
    p.unlink()
    audit.record(db, action="delete", entity_type="download", entity_id=name,
                 actor_id=actor.id, actor_username=actor.username, ip_address=client_ip(request))
    db.commit()
