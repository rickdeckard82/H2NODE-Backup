"""Validação do conteúdo de configurações de equipamentos de rede.

Usada duas vezes: na recepção (conteúdo ainda em claro, antes de cifrar) e na
verificação profunda (depois de decifrar). Formatos aceitos:

- texto puro (Datacom DmOS `show running-config`, Huawei .cfg, Fiberhome `config_<IP>_<data>`,
  MikroTik `/export`);
- gzip (Juniper archival: `<host>_juniper.conf.gz_AAAAMMDD_HHMMSS`);
- zip (Huawei pode enviar o `vrpcfg.zip`).
"""

import gzip
import hashlib
import io
import re
import zipfile
import zlib
from dataclasses import dataclass

VENDORS = ("datacom", "huawei", "juniper", "fiberhome", "mikrotik", "generic", "files")
VENDOR_LABEL = {
    "datacom": "Datacom (DmOS)",
    "huawei": "Huawei (VRP)",
    "juniper": "Juniper (Junos)",
    "fiberhome": "Fiberhome (OLT / UNM2000)",
    "mikrotik": "MikroTik (RouterOS)",
    "generic": "Genérico",
    "files": "Arquivos e bancos (FTP)",
}

_MAX_UNPACKED = 256 * 1024 * 1024  # proteção contra "zip bomb"

# Palavras de primeiro nível de um running-config DmOS (basta uma aparecer).
_DMOS_TOP_LEVEL = (
    "hostname", "aaa", "dot1q", "interface", "snmp", "sntp", "clock", "router", "vlan", "lldp",
    "license", "ip ", "ipv6", "switchport", "log", "access-list", "system", "config", "!",
    "service-port", "gpon", "dhcp", "mpls", "layer2", "ntp", "banner", "user",
)


# Cabeçalho do /export do RouterOS: "# 2026-10-18 03:00:01 by RouterOS 7.16.1" (v7) ou
# "# oct/18/2026 03:00:01 by RouterOS 6.49.10" (v6). Muda a cada exportação.
_ROS_HEADER = re.compile(rb"^#[^\n]* by RouterOS [^\n]*\n", re.MULTILINE)
# Mensagens do console do RouterOS quando o comando falha (não é uma exportação).
ROS_ERRORS = ("expected end of command", "bad command name", "syntax error", "not enough permissions",
              "no such item", "input does not match")


def content_sha256(data: bytes, vendor: str | None) -> str:
    """Hash usado para "idêntica ao backup anterior": ignora o que muda sozinho a cada
    exportação (no MikroTik, a linha de data do cabeçalho)."""
    if vendor == "mikrotik":
        data = _ROS_HEADER.sub(b"", data.replace(b"\r\n", b"\n"), count=1)
    return hashlib.sha256(data).hexdigest()


@dataclass
class ConfigCheck:
    ok: bool
    message: str
    lines: int = 0
    format: str = "text"  # text | gzip | zip


def _unpack(data: bytes) -> tuple[bytes, str]:
    if data[:2] == b"\x1f\x8b":
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        out = d.decompress(data, _MAX_UNPACKED)
        if d.unconsumed_tail:
            raise ValueError("arquivo descompactado grande demais")
        if not d.eof:
            raise ValueError("gzip truncado")
        return out, "gzip"
    if data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            bad = zf.testzip()
            if bad:
                raise ValueError(f"zip corrompido ({bad})")
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if not names:
                raise ValueError("zip vazio")
            # o arquivo de configuração é o maior dentro do zip
            name = max(names, key=lambda n: zf.getinfo(n).file_size)
            if zf.getinfo(name).file_size > _MAX_UNPACKED:
                raise ValueError("arquivo descompactado grande demais")
            return zf.read(name), "zip"
    return data, "text"


def looks_textual(b: bytes) -> bool:
    sample = b[:65536]
    if not sample:
        return False
    if b"\x00" in sample:
        return False
    printable = sum(1 for c in sample if c in (9, 10, 13) or 32 <= c < 127 or c >= 128)
    return printable / len(sample) > 0.95


def check(data: bytes, vendor: str | None) -> ConfigCheck:
    """Confere se `data` é uma configuração plausível do fabricante."""
    if not data:
        return ConfigCheck(False, "arquivo vazio")
    try:
        text_bytes, fmt = _unpack(data)
    except (ValueError, zipfile.BadZipFile, zlib.error, gzip.BadGzipFile, EOFError) as exc:
        return ConfigCheck(False, f"arquivo compactado inválido: {exc}")
    if not looks_textual(text_bytes):
        return ConfigCheck(False, "conteúdo não parece texto de configuração", format=fmt)
    text = text_bytes.decode("utf-8", errors="replace")
    lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    stripped = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(stripped) < 3:
        return ConfigCheck(False, "configuração com menos de 3 linhas", lines, fmt)

    if vendor == "huawei":
        # VRP termina a configuração salva com "return".
        if stripped[-1] != "return":
            return ConfigCheck(False, "configuração Huawei sem o \"return\" final (truncada?)", lines, fmt)
    elif vendor == "juniper":
        if "system {" not in text and not any(ln.startswith("set system ") for ln in stripped):
            return ConfigCheck(False, "configuração Junos sem o bloco \"system\"", lines, fmt)
        if text.count("{") != text.count("}"):
            return ConfigCheck(False, "chaves { } desbalanceadas (configuração truncada?)", lines, fmt)
    elif vendor == "fiberhome" and not (
        text.lstrip().startswith("!WOS system config") or any(ln.startswith("hostname ") for ln in stripped)
    ):
        return ConfigCheck(
            False, "não parece uma configuração de OLT Fiberhome (cabeçalho \"!WOS\" ou hostname ausente)",
            lines, fmt,
        )
    elif vendor == "mikrotik":
        low = text[:400].lower()
        if any(e in low for e in ROS_ERRORS):
            return ConfigCheck(False, "o RouterOS respondeu com erro em vez da exportação", lines, fmt)
        if "by routeros" not in low and not any(ln.startswith("/") for ln in stripped):
            return ConfigCheck(False, "não parece um /export do RouterOS", lines, fmt)
    elif vendor == "datacom" and not any(ln.startswith(_DMOS_TOP_LEVEL) for ln in stripped):
        return ConfigCheck(False, "não parece um running-config DmOS", lines, fmt)

    fmt_label = {"text": "texto", "gzip": "gzip", "zip": "zip"}[fmt]
    return ConfigCheck(True, f"configuração válida ({lines} linhas, {fmt_label})", lines, fmt)
