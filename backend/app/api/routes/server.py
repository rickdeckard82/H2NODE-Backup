from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse

from app.api.deps import require_auditor
from app.core.config import settings
from app.core.db import get_db
from app.models import SystemUser, WorkerStatus
from app.schemas.server import ServerInfoOut
from app.services import gpg, sshkeys, storage

router = APIRouter(prefix="/server", tags=["server"])


@router.get("/info", response_model=ServerInfoOut)
def server_info(db=Depends(get_db), _: SystemUser = Depends(require_auditor)) -> ServerInfoOut:
    pub = gpg.public_key_info()
    host_line, host_fp = sshkeys.host_key()
    disk = storage.disk_usage()
    ws = db.get(WorkerStatus, 1)
    return ServerInfoOut(
        public_key_available=pub is not None,
        public_key_fingerprint=pub.fingerprint if pub else None,
        public_key_uid=pub.uid if pub else None,
        deep_verify_enabled=bool(ws and ws.deep_verify),
        ssh_host=settings.ssh_public_host,
        ssh_port=settings.ssh_public_port,
        ssh_host_key=sshkeys.known_hosts_line(host_line) if host_line else None,
        ssh_host_key_fingerprint=host_fp,
        storage_path=settings.storage_path,
        disk_total_bytes=disk.total,
        disk_used_bytes=disk.used,
        disk_free_bytes=disk.free,
    )


@router.get("/public-key", response_class=PlainTextResponse)
def public_key(_: SystemUser = Depends(require_auditor)) -> PlainTextResponse:
    """Chave pública GPG (os clientes cifram para ela). Não é segredo, mas fica
    atrás do login para não expor a infraestrutura."""
    pub = gpg.public_key_info()
    if pub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chave pública não configurada no servidor")
    return PlainTextResponse(
        pub.armored, media_type="application/pgp-keys",
        headers={"Content-Disposition": 'attachment; filename="backup-key.pub.asc"'},
    )
