"""Envio por HTTPS — usado pelo cliente Windows (o agente Linux usa rsync/SSH).

Mesmo modelo de segurança do rrsync -wo: o cliente só CRIA execuções, ACRESCENTA
bytes aos arquivos (já cifrados com a chave pública) e FECHA a execução com o
manifest.json. Não lista, não lê conteúdo, não apaga, não renomeia. Tudo cai em
incoming/<cliente>/<execução>/ e segue o caminho normal do worker (ingest.py).

Autenticação: `Authorization: Bearer <token>` — um token por cliente, gerado no
painel (só o SHA-256 fica no banco). Sem cookie, então sem CSRF.

Retomada: GET .../files/<nome> devolve o tamanho já recebido; o PUT seguinte
manda `offset` igual a esse tamanho (se não bater: 409 com o tamanho atual).
"""

import contextlib
import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.logging import logger
from app.core.ratelimit import limiter
from app.models import Client
from app.services import gpg, storage
from app.services.manifest import MANIFEST_MAX_BYTES, MANIFEST_NAME, Manifest

router = APIRouter(prefix="/agent/v1", tags=["agent-upload"])

TOKEN_PREFIX = "pbu_"
CHUNK_MAX = 32 * 1024 * 1024        # o cliente manda pedaços de até 32 MiB
OPEN_RUNS_MAX = 5                   # execuções abertas (sem manifesto) por cliente
DISK_RESERVE = 2 * 1024 ** 3        # recusa envio com menos de 2 GiB livres

_RUN_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$")
_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,195}\.gpg$")


def new_token() -> tuple[str, str, str]:
    """(token, sha256, hint). O token só é mostrado uma vez."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_token(token), token[-6:]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class AgentClient:
    id: int
    slug: str
    name: str


def agent_client(request: Request, db: Session = Depends(get_db)) -> AgentClient:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.startswith(TOKEN_PREFIX) or len(token) > 200:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token ausente ou inválido",
                            headers={"WWW-Authenticate": "Bearer"})
    c = db.execute(select(Client).where(Client.upload_token_hash == hash_token(token))).scalar_one_or_none()
    if c is None or c.kind != "server":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido",
                            headers={"WWW-Authenticate": "Bearer"})
    if not c.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cliente inativo no painel")
    return AgentClient(id=c.id, slug=c.slug, name=c.name)


def _client_dir(ac: AgentClient) -> Path:
    storage.ensure_client_dirs(ac.slug)
    return storage.safe_child(storage.incoming(), ac.slug)


def _open_run(ac: AgentClient, run: str) -> Path:
    """Pasta de uma execução ainda aberta (existe e não tem manifesto)."""
    if not _RUN_RE.match(run):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "execução não encontrada")
    d = storage.safe_child(_client_dir(ac), run)
    if d.is_symlink() or not d.is_dir():
        # já processada pelo worker (foi para store/ ou quarentena) ou nunca existiu
        raise HTTPException(status.HTTP_404_NOT_FOUND, "execução não encontrada ou já recebida")
    if (d / MANIFEST_NAME).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "execução já fechada (manifesto recebido)")
    return d


def _file_path(run_dir: Path, name: str) -> Path:
    if not _FILE_RE.match(name):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "nome de arquivo inválido (precisa ser *.gpg)")
    p = storage.safe_child(run_dir, name)
    if p.is_symlink() or (p.exists() and not p.is_file()):
        raise HTTPException(status.HTTP_409_CONFLICT, "nome de arquivo em uso")
    return p


def _touch(run_dir: Path) -> None:
    # o worker manda para a quarentena execução parada há INCOMING_STALE_HOURS (mtime da pasta)
    with contextlib.suppress(OSError):
        os.utime(run_dir)


@router.get("/hello")
@limiter.limit("30/minute")
def hello(request: Request, ac: AgentClient = Depends(agent_client)) -> dict:
    """Confere o token e entrega o que o cliente precisa: a chave pública GPG (para
    cifrar) e os limites do envio."""
    pub = gpg.public_key_info()
    if pub is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "chave pública GPG não configurada no servidor")
    return {
        "client_id": ac.slug,
        "client_name": ac.name,
        "public_key": pub.armored,
        "public_key_fingerprint": pub.fingerprint,
        "chunk_max": CHUNK_MAX,
        "manifest_format": "h2node-backup/1",
        "server_time": datetime.now(UTC).isoformat(),
    }


@router.post("/runs", status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def create_run(request: Request, ac: AgentClient = Depends(agent_client)) -> dict:
    base = _client_dir(ac)
    open_runs = [d for d in base.iterdir()
                 if d.is_dir() and not d.name.startswith(".") and not (d / MANIFEST_NAME).exists()]
    if len(open_runs) >= OPEN_RUNS_MAX:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"{len(open_runs)} execuções abertas sem manifesto — "
                            "termine ou aguarde a limpeza")
    run = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    storage.safe_child(base, run).mkdir(mode=0o700)
    logger.info("agent_run_created", client=ac.slug, run=run)
    return {"run_name": run}


@router.get("/runs/{run}/files/{name}")
def file_status(run: str, name: str, ac: AgentClient = Depends(agent_client)) -> dict:
    """Quantos bytes deste arquivo já chegaram (para retomar o envio)."""
    p = _file_path(_open_run(ac, run), name)
    return {"size": p.stat().st_size if p.exists() else 0}


@router.put("/runs/{run}/files/{name}")
async def put_chunk(
    run: str, name: str, request: Request,
    offset: int = Query(ge=0),
    ac: AgentClient = Depends(agent_client),
) -> dict:
    """Acrescenta um pedaço ao arquivo, a partir de `offset` (= tamanho já recebido)."""
    run_dir = _open_run(ac, run)
    p = _file_path(run_dir, name)
    current = p.stat().st_size if p.exists() else 0
    if offset != current:
        # o cliente consulta o tamanho (GET) e retoma de lá
        raise HTTPException(status.HTTP_409_CONFLICT, f"offset {offset} ≠ {current} bytes já recebidos")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > CHUNK_MAX:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"pedaço maior que {CHUNK_MAX} bytes")
    if storage.disk_usage().free < DISK_RESERVE + CHUNK_MAX:
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, "servidor de backup sem espaço em disco")
    received = 0
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > CHUNK_MAX:
                # desfaz o pedaço inteiro: o arquivo volta ao tamanho de antes
                os.ftruncate(fd, current)
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"pedaço maior que {CHUNK_MAX} bytes")
            os.write(fd, chunk)
    except BaseException:
        if received <= CHUNK_MAX:
            os.ftruncate(fd, current)  # conexão caiu no meio: não deixa pedaço pela metade
        raise
    finally:
        os.close(fd)
    _touch(run_dir)
    return {"size": current + received}


@router.put("/runs/{run}/manifest")
async def put_manifest(run: str, request: Request, ac: AgentClient = Depends(agent_client)) -> dict:
    """Fecha a execução. Depois disto nada mais é aceito nela e o worker a recebe."""
    run_dir = _open_run(ac, run)
    body = await request.body()
    if len(body) > MANIFEST_MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "manifesto grande demais")
    try:
        m = Manifest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"manifesto inválido: {str(exc)[:500]}") from exc
    if m.client_id != ac.slug or m.run_name != run:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "client_id/run_name do manifesto não conferem")
    tmp = run_dir / ".manifest.tmp"
    tmp.write_bytes(body)
    os.replace(tmp, run_dir / MANIFEST_NAME)  # atômico: o worker só vê o manifesto inteiro
    logger.info("agent_run_closed", client=ac.slug, run=run, status=m.status, components=len(m.components))
    return {"ok": True}
