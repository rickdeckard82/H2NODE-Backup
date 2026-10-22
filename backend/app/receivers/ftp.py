"""Receptor FTP para equipamentos de rede (Huawei backup-to-server, Juniper archival…).

Regras:
- Conexão só de IPs cadastrados como equipamento FTP ativo — os demais são
  desconectados antes do login (nem chegam a tentar senha).
- Login com uma conta FTP do painel (hash Argon2id); 3 tentativas por conexão.
- Cada sessão grava numa pasta própria e vazia. Permissões: entrar/criar pasta,
  listar o que a própria sessão enviou, gravar e renomear — nunca ler (RETR)
  nem apagar. Pastas pedidas no caminho (ex.: "./192.0.2.15") são criadas.
- Arquivo completo vai para a fila do worker, atribuído ao equipamento pelo IP. No tipo
  "Arquivos e bancos" os arquivos ficam na pasta da sessão até o fim da conexão e vão juntos,
  como uma execução com uma parte por arquivo.
- Exceção de LEITURA, e só ela: o login do servidor de firmwares (página FTP Firmwares), de IP
  liberado para firmware, entra em STORAGE_PATH/firmware/files com permissão de listar e baixar
  — sem gravar, renomear, criar pasta nem apagar. Nenhum backup fica nessa pasta.

Uso: python -m app.receivers.ftp   (precisa de root só para abrir a porta 21)
"""

import os
import shutil
import signal
import uuid
from pathlib import Path

from pyftpdlib.authorizers import AuthenticationFailed, DummyAuthorizer
from pyftpdlib.filesystems import AbstractedFS
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.core.security import verify_password
from app.services import firmware, receivers

# e=CWD  l=LIST  m=MKD  w=STOR  f=RENAME  d=DELE/RMD — sem r (RETR), a (APPE), M (chmod).
# O "d" só deixa o comando CHEGAR ao handler: DELE/RMD continuam recusados (ver DeviceHandler),
# exceto como no-op para o gerenciador UNM2000.
PERMS = "elmwfd"
# Sessão de firmware: e=CWD  l=LIST  r=RETR — nada mais.
FIRMWARE_PERMS = "elr"

# IP de UNM2000 (campo "IP da UNM2000" das OLTs Fiberhome): depois que cada OLT envia o arquivo,
# a UNM2000 entra no FTP para apagar o antigo e RENOMEAR o novo. Aqui cada sessão é isolada e o
# arquivo já foi para a fila, então esses comandos respondem sucesso SEM fazer nada.
MANAGER_VENDOR = receivers.MANAGER_VENDOR


class AllowlistAuthorizer(DummyAuthorizer):
    """Valida conta + IP de origem contra o receivers.json (sem banco)."""

    def __init__(self, allowlist: receivers.Allowlist) -> None:
        super().__init__()
        self.allowlist = allowlist
        self._homes: dict[str, str] = {}

    def validate_authentication(self, username, password, handler):  # noqa: ANN001
        if self.allowlist.is_firmware_user(username):
            return self._firmware_login(username, password, handler)
        # a conta escolhe o cadastro quando o IP tem mais de um (ex.: serviços no mesmo servidor)
        device = self.allowlist.device(handler.remote_ip, "ftp", username)
        stored = self.allowlist.accounts.get(username)
        # verify_password roda mesmo com usuário inexistente (tempo constante)
        ok = verify_password(password, stored or receivers_dummy_hash())
        if device is None or stored is None or not ok:
            logger.warning("ftp_login_failed", ip=handler.remote_ip, user=username[:64])
            raise AuthenticationFailed("login inválido")
        home = receivers.netin() / ".sessions" / device.slug / uuid.uuid4().hex
        home.mkdir(parents=True, mode=0o700)
        handler.device = device
        handler.session_home = home
        # get_home_dir() é chamado logo em seguida, no mesmo ciclo do loop
        self._homes[username] = str(home)
        logger.info("ftp_login", ip=handler.remote_ip, user=username, device=device.slug)

    def _firmware_login(self, username, password, handler):  # noqa: ANN001
        ok = verify_password(password, self.allowlist.fw_hash or receivers_dummy_hash())
        home = firmware.files_dir()
        if not ok or not self.allowlist.firmware_allows(handler.remote_ip) or not home.is_dir():
            logger.warning("ftp_firmware_login_failed", ip=handler.remote_ip, user=username[:64])
            raise AuthenticationFailed("login inválido")
        handler.firmware = True
        self._homes[username] = str(home)
        logger.info("ftp_firmware_login", ip=handler.remote_ip, user=username)

    def get_home_dir(self, username):  # noqa: ANN001
        return self._homes.pop(username)

    def has_user(self, username):  # noqa: ANN001
        return True

    def _perms(self, username: str) -> str:
        return FIRMWARE_PERMS if self.allowlist.is_firmware_user(username) else PERMS

    def get_perms(self, username):  # noqa: ANN001
        return self._perms(username)

    def has_perm(self, username, perm, path=None):  # noqa: ANN001
        return perm in self._perms(username)

    def get_msg_login(self, username):  # noqa: ANN001
        if self.allowlist.is_firmware_user(username):
            return "Pulse Backup: firmwares (somente leitura)."
        return "Pulse Backup: somente envio de configuracao."

    def get_msg_quit(self, username):  # noqa: ANN001
        return "Ate logo."

    def impersonate_user(self, username, password):  # noqa: ANN001
        pass

    def terminate_impersonation(self, username):  # noqa: ANN001
        pass


_DUMMY: list[str] = []


def receivers_dummy_hash() -> str:
    if not _DUMMY:
        from app.core.security import DUMMY_PASSWORD_HASH

        _DUMMY.append(DUMMY_PASSWORD_HASH)
    return _DUMMY[0]


class AutoMkdirFS(AbstractedFS):
    """Cria as pastas do caminho no STOR/CWD (o Huawei manda "./<ip>/arquivo"
    sem criar a pasta antes). O handler já validou que o caminho está dentro
    da raiz da sessão (validpath)."""

    def _inside(self, path: str) -> bool:
        root = os.path.realpath(self.root)
        return os.path.realpath(path).startswith(root + os.sep) or os.path.realpath(path) == root

    def _firmware(self) -> bool:
        return getattr(self.cmd_channel, "firmware", False)

    def open(self, filename, mode):  # noqa: ANN001
        if self._firmware() and mode != "rb":
            raise PermissionError("somente leitura")
        if "w" in mode and self._inside(os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename), mode=0o700, exist_ok=True)
        return super().open(filename, mode)

    def chdir(self, path):  # noqa: ANN001
        if not self._firmware() and self._inside(path) and not os.path.exists(path):
            os.makedirs(path, mode=0o700, exist_ok=True)
        super().chdir(path)


class DeviceHandler(FTPHandler):
    abstracted_fs = AutoMkdirFS
    max_login_attempts = 3
    timeout = 300
    permit_foreign_addresses = False
    permit_privileged_ports = False

    def on_connect(self):  # noqa: D401
        self.device = None
        self.session_home = None
        self.firmware = False
        allow = self.server.allowlist
        if allow.device(self.remote_ip, "ftp") is None and not allow.firmware_allows(self.remote_ip):
            logger.warning("ftp_unknown_ip", ip=self.remote_ip)
            self.respond("421 IP nao autorizado.")
            self.close_when_done()

    def pre_process_command(self, line, cmd, arg):  # noqa: ANN001
        # sessão de firmware: só o que FIRMWARE_PERMS permite, conferido pela SESSÃO (o nome do
        # usuário no receivers.json pode mudar no meio da conexão)
        if self.firmware and self.authenticated:
            perm = self.proto_cmds.get(cmd, {}).get("perm")
            if perm and perm not in FIRMWARE_PERMS:
                self.respond("550 Somente leitura.")
                return None
        return super().pre_process_command(line, cmd, arg)

    def on_file_sent(self, file):  # noqa: ANN001
        if self.firmware:
            logger.info("ftp_firmware_sent", ip=self.remote_ip, file=os.path.basename(file))

    def _is_manager(self) -> bool:
        return getattr(getattr(self, "device", None), "vendor", None) == MANAGER_VENDOR

    def ftp_DELE(self, path):  # noqa: ANN001
        if not self._is_manager():
            self.respond("550 Not enough privileges.")
            return None
        logger.info("ftp_manager_noop", cmd="DELE", device=self.device.slug)
        self.respond("250 File removed.")
        return None

    def ftp_RMD(self, path):  # noqa: ANN001
        self.respond("550 Not enough privileges.")
        return None

    def ftp_RNFR(self, path):  # noqa: ANN001
        if not self._is_manager():
            return super().ftp_RNFR(path)
        self._rnfr = path
        self.respond("350 Ready for destination name.")
        return None

    def ftp_RNTO(self, path):  # noqa: ANN001
        if not self._is_manager():
            return super().ftp_RNTO(path)
        self._rnfr = None
        logger.info("ftp_manager_noop", cmd="RNTO", device=self.device.slug)
        self.respond("250 Renaming ok.")
        return None

    def on_file_received(self, file):  # noqa: ANN001
        path = Path(file)
        if self.firmware or self.device is None:  # não deveria acontecer (sem permissão de gravar)
            logger.error("ftp_unexpected_upload", ip=self.remote_ip, file=path.name)
            return
        size = path.stat().st_size
        # tipo "Arquivos e bancos" (dumps, .zip) tem limite próprio, maior que o de configuração
        files = getattr(self.device, "vendor", None) == receivers.FILES_VENDOR
        limit_mb = settings.net_files_max_mb if files else settings.net_max_file_mb
        if size > limit_mb * 1024 * 1024:
            logger.warning("ftp_file_too_large", ip=self.remote_ip, size=size, limit_mb=limit_mb)
            path.unlink(missing_ok=True)
            return
        if files:
            return  # fica na pasta da sessão: vai em lote no on_disconnect (uma execução, N partes)
        rel = os.path.relpath(file, self.session_home) if self.session_home else path.name
        receivers.finalize(path, self.device, protocol="ftp", remote_path=rel, size=size)

    def on_incomplete_file_received(self, file):  # noqa: ANN001
        Path(file).unlink(missing_ok=True)

    def on_disconnect(self):
        home = getattr(self, "session_home", None)
        if home is None:
            return
        try:
            if getattr(self.device, "vendor", None) == receivers.FILES_VENDOR:
                # O pyftpdlib já descartou o upload interrompido (on_incomplete_file_received é
                # chamado antes): o que sobrou são os arquivos completos, com o nome final se o
                # cliente renomeou (ex.: envio como .part + RNFR/RNTO).
                files = sorted((p for p in home.rglob("*") if p.is_file() and not p.is_symlink()),
                               key=lambda p: p.stat().st_mtime)
                receivers.finalize_batch([(p, os.path.relpath(p, home)) for p in files], self.device,
                                         protocol="ftp")
        except Exception as exc:  # noqa: BLE001
            logger.error("ftp_batch_failed", device=self.device.slug, error=str(exc))
        finally:
            shutil.rmtree(home, ignore_errors=True)


def build_server(host: str = "0.0.0.0", port: int | None = None,
                 allowlist: receivers.Allowlist | None = None) -> FTPServer:
    handler = DeviceHandler
    handler.authorizer = AllowlistAuthorizer(allowlist or receivers.Allowlist())
    handler.passive_ports = list(range(settings.passive_port_range[0], settings.passive_port_range[1] + 1))
    if settings.ftp_masquerade_address:
        handler.masquerade_address = settings.ftp_masquerade_address
    handler.banner = "Pulse Backup FTP"
    server = FTPServer((host, settings.ftp_port if port is None else port), handler)
    server.allowlist = handler.authorizer.allowlist
    server.max_cons = 64
    server.max_cons_per_ip = 4
    return server


def main() -> None:
    configure_logging()
    server = build_server(host=os.environ.get("FTP_BIND", "0.0.0.0"))
    receivers.drop_privileges()
    signal.signal(signal.SIGTERM, lambda *_: server.close_all())
    logger.info("ftp_listening", port=settings.ftp_port, passive=settings.ftp_passive_ports)
    server.serve_forever(handle_exit=True)


if __name__ == "__main__":
    main()
