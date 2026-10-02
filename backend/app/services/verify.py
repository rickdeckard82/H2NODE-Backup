"""Análise dos backups guardados.

Dois níveis, por componente (cada arquivo .gpg):

- **integridade** (sempre): SHA-256 do arquivo cifrado confere com o manifesto
  e o arquivo foi cifrado para a chave do servidor (senão ninguém conseguiria
  restaurar — erro comum ao trocar a chave e esquecer um cliente).
- **profunda** (com a chave privada no worker): decifra em streaming, sem gravar
  nada em disco, e testa o conteúdo:
    * pasta (.tar.gz): gzip íntegro (CRC) e tar legível até o fim; conta entradas;
    * MySQL/MariaDB/PostgreSQL (.sql.gz): gzip íntegro e o marcador de fim de
      dump presente (dump truncado não tem);
    * SQL Server (.bak.gz): gzip íntegro e cabeçalho MTF ("TAPE") do .bak;
    * SHA-256/tamanho do conteúdo decifrado batem com o que o agente calculou.
"""

import contextlib
import gzip
import hashlib
import subprocess
import tarfile
import tempfile
import threading
import zlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.core.security import utcnow
from app.models import Backup, BackupComponent, BackupStatus, VerifyStatus
from app.services import gpg, storage

_CHUNK = 1024 * 1024
_TAIL = 64 * 1024

SQL_END_MARKERS = {
    "mysql": (b"-- Dump completed",),
    "postgresql": (
        b"PostgreSQL database dump complete",
        b"PostgreSQL database cluster dump complete",
    ),
}


class CheckFailed(Exception):
    pass


@dataclass
class CompResult:
    ok: bool
    message: str
    item_count: int | None = None


class _HashingReader:
    """file-like sobre o stdout do gpg que calcula SHA-256 e tamanho."""

    def __init__(self, raw) -> None:
        self.raw = raw
        self.h = hashlib.sha256()
        self.n = 0

    def read(self, size: int = -1) -> bytes:
        data = self.raw.read(size if size and size > 0 else _CHUNK)
        if data:
            self.h.update(data)
            self.n += len(data)
        return data

    def drain(self) -> None:
        while self.read(_CHUNK):
            pass


def _check_tar(reader: _HashingReader) -> int:
    gz = gzip.GzipFile(fileobj=reader, mode="rb")
    count = 0
    with tarfile.open(fileobj=gz, mode="r|") as tf:
        for _member in tf:
            count += 1
    # lê o resto do gzip até o fim: só assim o CRC/tamanho do trailer é conferido
    while gz.read(_CHUNK):
        pass
    if count == 0:
        raise CheckFailed("arquivo tar vazio")
    return count


def _check_sql(reader: _HashingReader, kind: str) -> None:
    gz = gzip.GzipFile(fileobj=reader, mode="rb")
    tail = b""
    total = 0
    while chunk := gz.read(_CHUNK):
        total += len(chunk)
        tail = (tail + chunk)[-_TAIL:]
    if total == 0:
        raise CheckFailed("dump vazio")
    markers = SQL_END_MARKERS.get(kind, ())
    if markers and not any(m in tail for m in markers):
        raise CheckFailed("dump incompleto: marcador de fim ausente (o dump foi interrompido?)")


def _check_mssql(reader: _HashingReader) -> None:
    gz = gzip.GzipFile(fileobj=reader, mode="rb")
    head = gz.read(4)
    if head != b"TAPE":
        raise CheckFailed("não parece um .bak do SQL Server (cabeçalho MTF ausente)")
    while gz.read(_CHUNK):
        pass


def _content_check(reader: _HashingReader, comp: BackupComponent) -> int | None:
    name = comp.file_name or ""
    if comp.kind == "files" or name.endswith(".tar.gz.gpg"):
        return _check_tar(reader)
    if comp.kind in ("mysql", "postgresql"):
        _check_sql(reader, comp.kind)
        return None
    if comp.kind == "mssql":
        _check_mssql(reader)
        return None
    return None


def _deep_check(keyring: gpg.PrivateKeyring, path: Path, comp: BackupComponent) -> CompResult:
    cipher_hash = hashlib.sha256()
    write_error: list[BaseException] = []
    with tempfile.TemporaryFile() as errf:
        proc = subprocess.Popen(
            keyring.decrypt_cmd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errf,
        )

        def feed() -> None:
            try:
                with open(path, "rb") as f:
                    while chunk := f.read(_CHUNK):
                        cipher_hash.update(chunk)
                        proc.stdin.write(chunk)  # type: ignore[union-attr]
            except BrokenPipeError:
                pass
            except BaseException as exc:  # noqa: BLE001
                write_error.append(exc)
            finally:
                with contextlib.suppress(OSError):
                    proc.stdin.close()  # type: ignore[union-attr]

        writer = threading.Thread(target=feed, daemon=True)
        writer.start()
        reader = _HashingReader(proc.stdout)
        count: int | None = None
        failure: str | None = None
        try:
            count = _content_check(reader, comp)
            reader.drain()
        except CheckFailed as exc:
            failure = str(exc)
        except (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile, OSError) as exc:
            failure = f"conteúdo corrompido: {exc}"
        finally:
            if failure:
                proc.kill()
            proc.stdout.close()  # type: ignore[union-attr]
            rc = proc.wait()
            writer.join()
            errf.seek(0)
            stderr = errf.read().decode(errors="replace").strip()

    if write_error:
        return CompResult(False, f"erro lendo o arquivo: {write_error[0]}")
    if comp.sha256 and cipher_hash.hexdigest() != comp.sha256:
        return CompResult(False, "SHA-256 do arquivo cifrado mudou desde o recebimento (corrupção no disco?)")
    if failure:
        return CompResult(False, failure)
    if rc != 0:
        return CompResult(False, f"falha ao decifrar (gpg rc={rc}): {stderr[-300:]}")
    if comp.plain_sha256 and reader.h.hexdigest() != comp.plain_sha256:
        return CompResult(False, "SHA-256 do conteúdo decifrado não confere com o calculado no cliente")
    if comp.plain_size_bytes and reader.n != comp.plain_size_bytes:
        return CompResult(False, f"tamanho decifrado {reader.n} ≠ {comp.plain_size_bytes}")
    msg = "decifrado e testado"
    if count is not None:
        msg += f" ({count} entradas no tar)"
    return CompResult(True, msg, count)


def _integrity_check(path: Path, comp: BackupComponent) -> CompResult:
    from app.services.ingest import sha256_file

    if comp.sha256 and sha256_file(path) != comp.sha256:
        return CompResult(False, "SHA-256 do arquivo cifrado mudou desde o recebimento (corrupção no disco?)")
    return CompResult(True, "hash do arquivo cifrado confere")


def verify_component(keyring: gpg.PrivateKeyring | None, base: Path,
                     comp: BackupComponent, key_ids: set[str] | None) -> CompResult:
    try:
        path = storage.safe_child(base, comp.file_name or "")
    except ValueError as exc:
        return CompResult(False, str(exc))
    if path.is_symlink() or not path.is_file():
        return CompResult(False, "arquivo não encontrado no armazenamento")
    if key_ids:
        recips = gpg.recipient_key_ids(path)
        if not recips:
            return CompResult(False, "arquivo não é um pacote GPG cifrado válido")
        if not recips & key_ids:
            return CompResult(
                False,
                "cifrado para outra chave (" + ", ".join(sorted(recips))
                + ") — a chave do servidor NÃO consegue restaurar este backup",
            )
    if keyring is not None and keyring.available:
        return _deep_check(keyring, path, comp)
    return _integrity_check(path, comp)


def verify_backup(db: Session, backup: Backup, keyring: gpg.PrivateKeyring | None) -> None:
    if backup.storage_path is None or backup.deleted_at is not None:
        backup.verify_status = VerifyStatus.skipped
        backup.verify_message = "arquivos não estão mais no armazenamento"
        db.commit()
        return

    base = storage.root() / backup.storage_path
    pub = gpg.public_key_info()
    key_ids = pub.key_ids if pub else None
    deep = keyring is not None and keyring.available
    failures: list[str] = []
    checked = 0
    for comp in backup.components:
        if not comp.file_name:
            comp.verify_status = "skipped"
            comp.verify_message = "sem arquivo (falhou no cliente)"
            continue
        try:
            res = verify_component(keyring, base, comp, key_ids)
        except Exception as exc:  # noqa: BLE001
            logger.error("verify_component_error", backup=backup.id, file=comp.file_name, error=str(exc))
            res = CompResult(False, f"erro na verificação: {exc}")
        checked += 1
        comp.verify_status = "ok" if res.ok else "failed"
        comp.verify_message = res.message[:2000]
        if res.item_count is not None:
            comp.item_count = res.item_count
        if not res.ok:
            failures.append(f"{comp.name}: {res.message}")

    backup.verify_mode = "full" if deep else "integrity"
    backup.verified_at = utcnow()
    if failures:
        backup.verify_status = VerifyStatus.failed
        backup.verify_message = "; ".join(failures)[:4000]
        if backup.status in (BackupStatus.ok, BackupStatus.warning):
            backup.status = BackupStatus.corrupted
            latest = db.execute(
                select(Backup.id).where(Backup.client_id == backup.client_id)
                .order_by(Backup.received_at.desc()).limit(1)
            ).scalar_one_or_none()
            if latest == backup.id:
                backup.client.last_status = backup.status.value
    elif checked == 0:
        backup.verify_status = VerifyStatus.skipped
        backup.verify_message = "nenhum arquivo para verificar"
    else:
        backup.verify_status = VerifyStatus.ok
        backup.verify_message = (
            f"{checked} arquivo(s) decifrado(s) e testado(s)" if deep
            else f"{checked} arquivo(s) íntegro(s) — sem chave privada, conteúdo não testado"
        )
    db.commit()
    logger.info("verify_done", backup=backup.id, status=backup.verify_status.value,
                mode=backup.verify_mode)
