"""Teste do conteúdo dos arquivos do tipo "Arquivos e bancos" (enviados por FTP).

Roda na recepção, sobre o arquivo ainda em claro no disco (antes de cifrar), sempre
em streaming — o arquivo pode ter GB. Pela extensão:

- .sql / .sql.gz: dump do mysqldump/mariadb-dump ou do pg_dump/pg_dumpall, com o
  marcador de fim (dump interrompido não tem). SQL sem o cabeçalho dessas
  ferramentas é guardado com aviso: não dá para confirmar que está completo;
- .zip: CRC de todos os arquivos de dentro;
- .tar.gz/.tgz: gzip íntegro e tar legível até o fim; .gz: gzip íntegro;
- .pdf: cabeçalho %PDF e marcador %%EOF no fim;
- texto (.conf, .txt, .csv…): sem bytes binários;
- outros formatos: só guardados.

A verificação profunda (verify.py) confere o SHA-256 do conteúdo decifrado contra o
calculado na recepção: o que foi testado aqui é o que está guardado.
"""

import gzip
import tarfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from app.services.netconfig import looks_textual

_CHUNK = 1024 * 1024
_TAIL = 64 * 1024

TEXT_EXTS = (".conf", ".cfg", ".cnf", ".ini", ".txt", ".csv", ".tsv", ".json", ".xml", ".yml", ".yaml",
             ".log", ".md")
MYSQL_HEADS = (b"-- MySQL dump", b"-- MariaDB dump")
PG_HEADS = (b"-- PostgreSQL database dump", b"-- PostgreSQL database cluster dump")
KIND_LABEL = {"mysql": "MySQL/MariaDB", "postgresql": "PostgreSQL"}


@dataclass
class FileCheck:
    status: str  # ok | warning | failed
    message: str
    kind: str = "file"  # file | mysql | postgresql (tipo do componente)
    items: int | None = None

    @property
    def ok(self) -> bool:
        return self.status != "failed"


def _open(path: Path):
    with open(path, "rb") as f:
        magic = f.read(2)
    return gzip.open(path, "rb") if magic == b"\x1f\x8b" else open(path, "rb")  # noqa: SIM115


def _check_sql(path: Path) -> FileCheck:
    from app.services.verify import SQL_END_MARKERS

    head = tail = b""
    total = 0
    with _open(path) as f:
        while chunk := f.read(_CHUNK):
            if len(head) < _TAIL:
                head += chunk[: _TAIL - len(head)]
            total += len(chunk)
            tail = (tail + chunk)[-_TAIL:]
    if total == 0:
        return FileCheck("failed", "dump vazio")
    if not looks_textual(head):
        return FileCheck("failed", "não parece um dump SQL (conteúdo binário)")
    kind = ("mysql" if any(h in head for h in MYSQL_HEADS)
            else "postgresql" if any(h in head for h in PG_HEADS) else None)
    if kind is None:
        return FileCheck("warning", "SQL sem o cabeçalho do mysqldump/pg_dump: não dá para confirmar "
                                    "que o dump está completo")
    if not any(m in tail for m in SQL_END_MARKERS[kind]):
        return FileCheck("failed", "dump incompleto: marcador de fim ausente (o dump foi interrompido?)",
                         kind)
    return FileCheck("ok", f"dump {KIND_LABEL[kind]} completo", kind)


def _check_zip(path: Path) -> FileCheck:
    with zipfile.ZipFile(path) as zf:
        files = [i for i in zf.infolist() if not i.is_dir()]
        if not files:
            return FileCheck("failed", "zip vazio")
        try:
            bad = zf.testzip()
        except RuntimeError:  # "password required"
            return FileCheck("warning",
                             f"zip protegido por senha ({len(files)} arquivo(s)): conteúdo não testado",
                             items=len(files))
    if bad:
        return FileCheck("failed", f"zip corrompido ({bad})")
    return FileCheck("ok", f"zip íntegro ({len(files)} arquivo(s))", items=len(files))


def _check_tar_gz(path: Path) -> FileCheck:
    count = 0
    with gzip.open(path, "rb") as gz:
        with tarfile.open(fileobj=gz, mode="r|") as tf:
            for _member in tf:
                count += 1
        while gz.read(_CHUNK):  # até o fim: confere o CRC do gzip
            pass
    if count == 0:
        return FileCheck("failed", "arquivo tar vazio")
    return FileCheck("ok", f"tar.gz íntegro ({count} entradas)", items=count)


def _check_gz(path: Path) -> FileCheck:
    with gzip.open(path, "rb") as gz:
        while gz.read(_CHUNK):
            pass
    return FileCheck("ok", "gzip íntegro")


def _check_pdf(path: Path) -> FileCheck:
    with open(path, "rb") as f:
        head = f.read(1024)
        f.seek(max(0, path.stat().st_size - 2048))
        tail = f.read()
    if b"%PDF-" not in head:
        return FileCheck("failed", "não parece um PDF (cabeçalho %PDF ausente)")
    if b"%%EOF" not in tail:
        return FileCheck("failed", "PDF incompleto (marcador %%EOF ausente no fim)")
    return FileCheck("ok", "PDF completo")


def _check_text(path: Path) -> FileCheck:
    lines = 0
    with open(path, "rb") as f:
        head = f.read(_TAIL)
        if not looks_textual(head):
            return FileCheck("failed", "não parece texto (conteúdo binário)")
        lines = head.count(b"\n")
        while chunk := f.read(_CHUNK):
            lines += chunk.count(b"\n")
    return FileCheck("ok", f"texto ({lines} linhas)", items=lines)


def check_file(path: Path, name: str) -> FileCheck:
    """Testa o arquivo recebido em `path`; `name` (nome enviado) define o formato."""
    if path.stat().st_size == 0:
        return FileCheck("failed", "arquivo vazio")
    n = name.lower()
    try:
        if n.endswith((".sql", ".sql.gz")):
            return _check_sql(path)
        if n.endswith(".zip"):
            return _check_zip(path)
        if n.endswith((".tar.gz", ".tgz")):
            return _check_tar_gz(path)
        if n.endswith(".gz"):
            return _check_gz(path)
        if n.endswith(".pdf"):
            return _check_pdf(path)
        if n.endswith(TEXT_EXTS):
            return _check_text(path)
    except zipfile.BadZipFile as exc:
        return FileCheck("failed", f"zip corrompido: {exc}")
    except (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile, OSError) as exc:
        return FileCheck("failed", f"arquivo corrompido: {exc}")
    return FileCheck("ok", "arquivo guardado (formato sem teste de conteúdo)")
