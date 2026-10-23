"""Receptor TFTP (RFC 1350 + opções RFC 2347/2348/2349).

- WRQ (upload de backup) só de IPs cadastrados como equipamento TFTP ativo.
- RRQ (download) serve SÓ o servidor de firmwares (STORAGE_PATH/firmware/files), para IPs
  liberados na página FTP Firmwares. Nenhum backup é lido por aqui.
- O caminho pedido pelo equipamento (ex.: "DM4380MP/config.txt") é só um rótulo:
  o arquivo vai para a área do equipamento identificado pelo IP de origem.
- Tamanho máximo NET_MAX_FILE_MB; transferências simultâneas limitadas.

Uso: python -m app.receivers.tftp   (precisa de root só para abrir a porta 69)
"""

import os
import signal
import socket
import struct
import tempfile
import threading
import time
from pathlib import Path

from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.services import firmware, receivers

OP_RRQ, OP_WRQ, OP_DATA, OP_ACK, OP_ERROR, OP_OACK = 1, 2, 3, 4, 5, 6
ERR_NOT_DEFINED, ERR_NOT_FOUND, ERR_ACCESS, ERR_DISK_FULL = 0, 1, 2, 3
ERR_ILLEGAL_OP, ERR_UNKNOWN_TID, ERR_OPTION = 4, 5, 8

DEFAULT_BLKSIZE = 512
MAX_BLKSIZE = 8192
RETRIES = 5
MAX_TRANSFERS = 32

_slots = threading.BoundedSemaphore(MAX_TRANSFERS)

# leituras de firmware em andamento (monitor da página FTP Firmwares)
_reads: dict[int, "ReadTransfer"] = {}
_reads_lock = threading.Lock()
_fw_status = firmware.StatusPublisher("tftp")


def publish_status(force: bool = False) -> None:
    with _reads_lock:
        sessions = [{"id": f"tftp-{id(t):x}", "ip": t.addr[0], "user": None, "since": t.since,
                     "file": t.path.name, "sent": t.sent, "size": t.size} for t in _reads.values()]
    try:
        _fw_status.publish(sorted(sessions, key=lambda s: s["since"]), force=force)
    except Exception as exc:  # noqa: BLE001  (o monitor nunca derruba o receptor)
        logger.warning("tftp_status_failed", error=str(exc))


def error_packet(code: int, msg: str) -> bytes:
    return struct.pack("!HH", OP_ERROR, code) + msg.encode("ascii", "replace")[:200] + b"\0"


def parse_request(pkt: bytes) -> tuple[int, str, str, dict[str, str]]:
    """(opcode, nome, modo, opções). Levanta ValueError se malformado."""
    if len(pkt) < 4:
        raise ValueError("pacote curto")
    (op,) = struct.unpack("!H", pkt[:2])
    parts = pkt[2:].split(b"\0")
    if len(parts) < 3:
        raise ValueError("requisição malformada")
    fields = [p.decode("ascii", "replace") for p in parts[:-1]]
    filename, mode = fields[0], fields[1].lower()
    opts = {fields[i].lower(): fields[i + 1] for i in range(2, len(fields) - 1, 2)}
    if not filename or mode not in ("octet", "netascii"):
        raise ValueError(f"modo não suportado: {mode}")
    return op, filename, mode, opts


class Transfer(threading.Thread):
    def __init__(self, server: "TftpServer", addr: tuple, device: receivers.Device,
                 filename: str, mode: str, opts: dict[str, str]) -> None:
        super().__init__(daemon=True)
        self.server, self.addr, self.device = server, addr, device
        self.filename, self.mode, self.opts = filename, mode, opts
        self.max_bytes = settings.net_max_file_mb * 1024 * 1024

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            logger.error("tftp_transfer_error", ip=self.addr[0], error=str(exc))
        finally:
            _slots.release()

    def _negotiate(self) -> tuple[int, float, dict[str, str]]:
        blksize, timeout, accepted = DEFAULT_BLKSIZE, 3.0, {}
        if "blksize" in self.opts:
            try:
                b = int(self.opts["blksize"])
                if 8 <= b <= 65464:
                    blksize = min(b, MAX_BLKSIZE)
                    accepted["blksize"] = str(blksize)
            except ValueError:
                pass
        if "timeout" in self.opts:
            try:
                t = int(self.opts["timeout"])
                if 1 <= t <= 255:
                    timeout = float(t)
                    accepted["timeout"] = str(t)
            except ValueError:
                pass
        if "tsize" in self.opts:
            try:
                ts = int(self.opts["tsize"])
            except ValueError:
                ts = 0
            if ts > self.max_bytes:
                raise OverflowError
            accepted["tsize"] = str(ts)
        return blksize, timeout, accepted

    def _run(self) -> None:
        family = socket.AF_INET6 if ":" in self.addr[0] else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_DGRAM)
        sock.bind((self.server.bind_host if family == self.server.family else "", 0))
        try:
            try:
                blksize, timeout, accepted = self._negotiate()
            except OverflowError:
                sock.sendto(error_packet(ERR_DISK_FULL, "arquivo grande demais"), self.addr)
                return
            sock.settimeout(timeout)
            if accepted:
                body = b"".join(k.encode() + b"\0" + v.encode() + b"\0" for k, v in accepted.items())
                last = struct.pack("!H", OP_OACK) + body
            else:
                last = struct.pack("!HH", OP_ACK, 0)
            sock.sendto(last, self.addr)

            tmpdir = receivers.netin() / ".tmp"
            tmpdir.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, tmp = tempfile.mkstemp(dir=tmpdir, prefix="tftp-")
            ok = False
            total = 0
            try:
                with os.fdopen(fd, "wb") as out:
                    expected = 1
                    retries = 0
                    while True:
                        try:
                            pkt, addr = sock.recvfrom(blksize + 4)
                        except TimeoutError:
                            retries += 1
                            if retries > RETRIES:
                                logger.warning("tftp_timeout", ip=self.addr[0], file=self.filename)
                                return
                            sock.sendto(last, self.addr)
                            continue
                        if addr != self.addr:
                            sock.sendto(error_packet(ERR_UNKNOWN_TID, "TID desconhecido"), addr)
                            continue
                        if len(pkt) < 4:
                            continue
                        op, block = struct.unpack("!HH", pkt[:4])
                        if op == OP_ERROR:
                            logger.warning("tftp_client_error", ip=self.addr[0], msg=pkt[4:-1][:100])
                            return
                        if op != OP_DATA:
                            sock.sendto(error_packet(ERR_ILLEGAL_OP, "esperava DATA"), self.addr)
                            return
                        if block == expected:
                            data = pkt[4:]
                            total += len(data)
                            if total > self.max_bytes:
                                sock.sendto(error_packet(ERR_DISK_FULL, "arquivo grande demais"), self.addr)
                                return
                            out.write(data)
                            last = struct.pack("!HH", OP_ACK, block)
                            sock.sendto(last, self.addr)
                            retries = 0
                            if len(data) < blksize:
                                ok = True
                                break
                            expected = (expected + 1) % 65536
                        elif block == (expected - 1) % 65536:
                            sock.sendto(last, self.addr)  # DATA repetido: o ACK se perdeu
                # "dally": se o último ACK se perder, o cliente reenvia o último DATA
                sock.settimeout(1.0)
                try:
                    pkt, addr = sock.recvfrom(blksize + 4)
                    if addr == self.addr:
                        sock.sendto(last, self.addr)
                except (TimeoutError, OSError):
                    pass
                if self.mode == "netascii":
                    p = Path(tmp)
                    p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\r\0", b"\r"))
                    total = p.stat().st_size
                receivers.finalize(Path(tmp), self.device, protocol="tftp",
                                   remote_path=self.filename, size=total)
            finally:
                if not ok:
                    Path(tmp).unlink(missing_ok=True)
        finally:
            sock.close()


class ReadTransfer(threading.Thread):
    """Envia um firmware (RRQ). Blocos de até MAX_BLKSIZE; acima de 65535 blocos o número
    volta a 0 (o que tftp-hpa, U-Boot e os switches esperam)."""

    def __init__(self, server: "TftpServer", addr: tuple, path: Path, opts: dict[str, str]) -> None:
        super().__init__(daemon=True)
        self.server, self.addr, self.path, self.opts = server, addr, path, opts
        self.since, self.sent, self.size = time.time(), 0, None

    def run(self) -> None:
        with _reads_lock:
            _reads[id(self)] = self
        publish_status(force=True)
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            logger.error("tftp_read_error", ip=self.addr[0], file=self.path.name, error=str(exc))
        finally:
            with _reads_lock:
                _reads.pop(id(self), None)
            _slots.release()
            publish_status(force=True)

    def _negotiate(self, size: int) -> tuple[int, float, dict[str, str]]:
        blksize, timeout, accepted = DEFAULT_BLKSIZE, 3.0, {}
        if "blksize" in self.opts:
            try:
                b = int(self.opts["blksize"])
                if 8 <= b <= 65464:
                    blksize = min(b, MAX_BLKSIZE)
                    accepted["blksize"] = str(blksize)
            except ValueError:
                pass
        if "timeout" in self.opts:
            try:
                t = int(self.opts["timeout"])
                if 1 <= t <= 255:
                    timeout = float(t)
                    accepted["timeout"] = str(t)
            except ValueError:
                pass
        if "tsize" in self.opts:
            accepted["tsize"] = str(size)  # no RRQ o servidor informa o tamanho
        return blksize, timeout, accepted

    def _exchange(self, sock: socket.socket, pkt: bytes, block: int, blksize: int) -> bool:
        """Envia `pkt` e espera o ACK de `block`, reenviando no timeout."""
        sock.sendto(pkt, self.addr)
        retries = 0
        while True:
            try:
                data, addr = sock.recvfrom(blksize + 4)
            except TimeoutError:
                retries += 1
                if retries > RETRIES:
                    logger.warning("tftp_timeout", ip=self.addr[0], file=self.path.name)
                    return False
                sock.sendto(pkt, self.addr)
                continue
            if addr != self.addr:
                sock.sendto(error_packet(ERR_UNKNOWN_TID, "TID desconhecido"), addr)
                continue
            if len(data) < 4:
                continue
            op, n = struct.unpack("!HH", data[:4])
            if op == OP_ERROR:
                logger.warning("tftp_client_error", ip=self.addr[0], msg=data[4:-1][:100])
                return False
            if op != OP_ACK:
                sock.sendto(error_packet(ERR_ILLEGAL_OP, "esperava ACK"), self.addr)
                return False
            if n == block:
                return True
            # ACK antigo/duplicado: ignora (sem reenviar, evita a "síndrome do aprendiz de feiticeiro")

    def _run(self) -> None:
        family = socket.AF_INET6 if ":" in self.addr[0] else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_DGRAM)
        sock.bind((self.server.bind_host if family == self.server.family else "", 0))
        try:
            with open(self.path, "rb") as f:
                size = self.size = os.fstat(f.fileno()).st_size
                blksize, timeout, accepted = self._negotiate(size)
                sock.settimeout(timeout)
                if accepted:
                    body = b"".join(k.encode() + b"\0" + v.encode() + b"\0" for k, v in accepted.items())
                    if not self._exchange(sock, struct.pack("!H", OP_OACK) + body, 0, blksize):
                        return
                block = 0
                while True:
                    chunk = f.read(blksize)
                    block = (block + 1) % 65536
                    if not self._exchange(sock, struct.pack("!HH", OP_DATA, block) + chunk, block, blksize):
                        return
                    self.sent += len(chunk)
                    if len(chunk) < blksize:
                        break
            logger.info("tftp_firmware_sent", ip=self.addr[0], file=self.path.name, size=size)
        finally:
            sock.close()


class TftpServer:
    def __init__(self, host: str = "0.0.0.0", port: int | None = None,
                 allowlist: receivers.Allowlist | None = None) -> None:
        self.bind_host = host
        self.family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self.sock = socket.socket(self.family, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, settings.tftp_port if port is None else port))
        self.port = self.sock.getsockname()[1]
        self.allowlist = allowlist or receivers.Allowlist()
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()
        self.sock.close()

    def handle(self, pkt: bytes, addr: tuple) -> None:
        ip = addr[0]
        try:
            op, filename, mode, opts = parse_request(pkt)
        except (ValueError, struct.error):
            self.sock.sendto(error_packet(ERR_ILLEGAL_OP, "requisição inválida"), addr)
            return
        if op == OP_RRQ:
            if not self.allowlist.firmware_allows(ip):
                logger.warning("tftp_read_refused", ip=ip, file=filename)
                self.sock.sendto(error_packet(ERR_ACCESS, "leitura não permitida"), addr)
                return
            try:
                path = firmware.resolve(filename)
            except (ValueError, OSError):
                path = None
            if path is None:
                logger.warning("tftp_firmware_not_found", ip=ip, file=filename[:200])
                self.sock.sendto(error_packet(ERR_NOT_FOUND, "arquivo nao encontrado"), addr)
                return
            if not _slots.acquire(blocking=False):
                self.sock.sendto(error_packet(ERR_NOT_DEFINED, "servidor ocupado, tente de novo"), addr)
                return
            ReadTransfer(self, addr, path, opts).start()
            return
        if op != OP_WRQ:
            self.sock.sendto(error_packet(ERR_ILLEGAL_OP, "operação inválida"), addr)
            return
        device = self.allowlist.device(ip, "tftp")
        if device is None:
            logger.warning("tftp_unknown_ip", ip=ip, file=filename)
            self.sock.sendto(error_packet(ERR_ACCESS, "IP não autorizado"), addr)
            return
        if not _slots.acquire(blocking=False):
            self.sock.sendto(error_packet(ERR_NOT_DEFINED, "servidor ocupado, tente de novo"), addr)
            return
        Transfer(self, addr, device, filename, mode, opts).start()

    def _publisher(self) -> None:
        while not self._stop.wait(firmware.STATUS_EVERY):
            publish_status()

    def serve_forever(self) -> None:
        logger.info("tftp_listening", host=self.bind_host, port=self.port)
        threading.Thread(target=self._publisher, daemon=True).start()
        while not self._stop.is_set():
            try:
                pkt, addr = self.sock.recvfrom(1024)
            except OSError:
                if self._stop.is_set():
                    break
                continue
            self.handle(pkt, addr)


def main() -> None:
    configure_logging()
    server = TftpServer(host=os.environ.get("TFTP_BIND", "0.0.0.0"))
    receivers.drop_privileges()
    signal.signal(signal.SIGTERM, lambda *_: server.stop())
    server.serve_forever()


if __name__ == "__main__":
    main()
