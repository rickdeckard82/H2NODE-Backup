"""Receptor FTP para equipamentos de rede (Huawei backup-to-server, Juniper archival…).

Regras:
- Conexão só de IPs cadastrados como equipamento FTP ativo — os demais são
  desconectados antes do login (nem chegam a tentar senha).
- Login com uma conta FTP do painel (hash Argon2id); 3 tentativas por conexão.
- Cada sessão grava numa pasta própria e vazia. Permissões: entrar/criar pasta,
  listar o que a própria sessão enviou, gravar e renomear — nunca ler (RETR)
  nem apagar. Pastas pedidas no caminho (ex.: "./192.0.2.15") são criadas.
- Arquivo completo vai para a fila do worker, atribuído ao equipamento pelo IP.

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
from app.services import receivers

# e=CWD  l=LIST  m=MKD  w=STOR  f=RENAME  d=DELE/RMD — sem r (RETR), a (APPE), M (chmod).
# O "d" só deixa o comando CHEGAR ao handler: DELE/RMD continuam recusados (ver DeviceHandler),
# exceto como no-op para o gerenciador UNM2000.
PERMS = "elmwfd"

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
        device = self.allowlist.device(handler.remote_ip, "ftp")
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

    def get_home_dir(self, username):  # noqa: ANN001
        return self._homes.pop(username)

    def has_user(self, username):  # noqa: ANN001
        return True

    def get_perms(self, username):  # noqa: ANN001
        return PERMS

    def has_perm(self, username, perm, path=None):  # noqa: ANN001
        return perm in PERMS

    def get_msg_login(self, username):  # noqa: ANN001
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

    def open(self, filename, mode):  # noqa: ANN001
        if "w" in mode and self._inside(os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename), mode=0o700, exist_ok=True)
        return super().open(filename, mode)

    def chdir(self, path):  # noqa: ANN001
        if self._inside(path) and not os.path.exists(path):
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
        if self.server.allowlist.device(self.remote_ip, "ftp") is None:
            logger.warning("ftp_unknown_ip", ip=self.remote_ip)
            self.respond("421 IP nao autorizado.")
            self.close_when_done()

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
        size = path.stat().st_size
        if size > settings.net_max_file_mb * 1024 * 1024:
            logger.warning("ftp_file_too_large", ip=self.remote_ip, size=size)
            path.unlink(missing_ok=True)
            return
        rel = os.path.relpath(file, self.session_home) if self.session_home else path.name
        receivers.finalize(path, self.device, protocol="ftp", remote_path=rel, size=size)

    def on_incomplete_file_received(self, file):  # noqa: ANN001
        Path(file).unlink(missing_ok=True)

    def on_disconnect(self):
        home = getattr(self, "session_home", None)
        if home is not None:
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
