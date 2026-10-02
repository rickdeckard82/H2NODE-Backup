"""Validação do conteúdo de configurações de equipamentos de rede.

Usada duas vezes: na recepção (conteúdo ainda em claro, antes de cifrar) e na
verificação profunda (depois de decifrar). Formatos aceitos:

- texto puro (Datacom DmOS `show running-config`, Huawei .cfg);
- gzip (Juniper archival: `<host>_juniper.conf.gz_AAAAMMDD_HHMMSS`);
- zip (Huawei pode enviar o `vrpcfg.zip`).
"""

import gzip
import io
import zipfile
import zlib
from dataclasses import dataclass

VENDORS = ("datacom", "huawei", "juniper", "generic")
VENDOR_LABEL = {
    "datacom": "Datacom (DmOS)",
    "huawei": "Huawei (VRP)",
    "juniper": "Juniper (Junos)",
    "generic": "Genérico",
}

_MAX_UNPACKED = 256 * 1024 * 1024  # proteção contra "zip bomb"

# Palavras de primeiro nível de um running-config DmOS (basta uma aparecer).
_DMOS_TOP_LEVEL = (
    "hostname", "aaa", "dot1q", "interface", "snmp", "sntp", "clock", "router", "vlan", "lldp",
    "license", "ip ", "ipv6", "switchport", "log", "access-list", "system", "config", "!",
    "service-port", "gpon", "dhcp", "mpls", "layer2", "ntp", "banner", "user",
)


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


def _looks_textual(b: bytes) -> bool:
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
    if not _looks_textual(text_bytes):
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
    elif vendor == "datacom" and not any(ln.startswith(_DMOS_TOP_LEVEL) for ln in stripped):
        return ConfigCheck(False, "não parece um running-config DmOS", lines, fmt)

    fmt_label = {"text": "texto", "gzip": "gzip", "zip": "zip"}[fmt]
    return ConfigCheck(True, f"configuração válida ({lines} linhas, {fmt_label})", lines, fmt)
