"""MikroTik: validação do /export, credenciais e cadastro pela API e coleta por SSH
contra um servidor SSH de verdade (paramiko imitando o RouterOS) em 127.0.0.1."""

import json
import socket
import threading
from datetime import timedelta
from pathlib import Path

import paramiko
import pytest

from app.core import crypto
from app.core.config import settings
from app.core.security import utcnow
from app.models import Backup, BackupStatus, Client, DeviceCredential, VerifyStatus
from app.services import mikrotik, netconfig, receivers, verify
from tests.test_pipeline import keyring, keys  # noqa: F401  (fixtures)

ROS7_EXPORT = (b"# 2026-10-18 03:00:01 by RouterOS 7.16.1\r\n# software id = ABCD-1234\r\n#\r\n"
               b"/interface bridge\r\nadd name=bridge1\r\n/ip address\r\n"
               b"add address=10.0.0.1/24 interface=bridge1\r\n/system identity\r\nset name=RB-CORE\r\n")
ROS6_EXPORT = (b"# oct/18/2026 03:00:01 by RouterOS 6.49.10\r\n# software id = ABCD-1234\r\n"
               b"/system identity\r\nset name=RB-OLD\r\n/ip address\r\n"
               b"add address=10.0.0.2/24 interface=ether1\r\n")
USER, PASSWORD = "pulse-backup", "Senha-forte-1"


# ------------------------------------------------------------------ netconfig --


def test_netconfig_mikrotik():
    assert netconfig.check(ROS7_EXPORT, "mikrotik").ok
    assert netconfig.check(ROS6_EXPORT, "mikrotik").ok
    bad = b"expected end of command (line 1 column 9)\r\n\r\n\r\n"
    assert not netconfig.check(bad * 2, "mikrotik").ok
    assert not netconfig.check(b"ola\nmundo\nqualquer\ncoisa\n", "mikrotik").ok
    # a linha de data do cabeçalho não conta para "idêntica ao anterior"
    later = ROS7_EXPORT.replace(b"2026-10-18 03:00:01", b"2026-10-19 03:00:02")
    assert netconfig.content_sha256(ROS7_EXPORT, "mikrotik") == netconfig.content_sha256(later, "mikrotik")
    changed = later.replace(b"RB-CORE", b"RB-EDGE")
    assert netconfig.content_sha256(ROS7_EXPORT, "mikrotik") != netconfig.content_sha256(changed, "mikrotik")
    # outros fabricantes: hash do arquivo inteiro
    assert netconfig.content_sha256(ROS7_EXPORT, "huawei") != netconfig.content_sha256(later, "huawei")


# ------------------------------------------------------------- RouterOS falso --


class _RosServer(paramiko.ServerInterface):
    def __init__(self, owner: "FakeRouterOS") -> None:
        self.owner = owner

    def get_allowed_auths(self, username):  # noqa: ANN001
        return "password"

    def check_auth_password(self, username, password):  # noqa: ANN001
        ok = (username, password) == (USER, PASSWORD)
        return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):  # noqa: ANN001
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):  # noqa: ANN001
        cmd = command.decode()
        self.owner.commands.append(cmd)
        if cmd == "/export show-sensitive" and self.owner.v6:
            out = b"expected end of command (line 1 column 9)\r\n"
        elif cmd in ("/export", "/export show-sensitive"):
            out = self.owner.export
        else:
            out = b"bad command name\r\n"

        def reply() -> None:
            channel.sendall(out)
            channel.send_exit_status(0)
            channel.close()

        threading.Thread(target=reply, daemon=True).start()
        return True


class FakeRouterOS:
    def __init__(self, export: bytes = ROS7_EXPORT, v6: bool = False) -> None:
        self.export, self.v6 = export, v6
        self.commands: list[str] = []
        self.host_key = paramiko.ECDSAKey.generate()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def new_host_key(self) -> None:
        self.host_key = paramiko.ECDSAKey.generate()

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(self.host_key)
            try:
                t.start_server(server=_RosServer(self))
            except paramiko.SSHException:
                continue

    def close(self) -> None:
        self._stop = True
        self.sock.close()


@pytest.fixture
def ros():
    srv = FakeRouterOS()
    yield srv
    srv.close()


@pytest.fixture
def rb(db, ros):
    cred = DeviceCredential(name="padrão", username=USER, password_enc=crypto.encrypt(PASSWORD),
                            port=ros.port)
    db.add(cred)
    db.flush()
    c = Client(slug="rb-core", name="RB Core", kind="network", vendor="mikrotik", protocol="ssh",
               mgmt_ip="127.0.0.1", pull_credential_id=cred.id, expected_interval_hours=24,
               retention_days=30, retention_min_keep=3)
    db.add(c)
    db.commit()
    return c


def pull(db) -> int:
    jobs = mikrotik.claim_due(db)
    for j in jobs:
        try:
            res = mikrotik.fetch_export(j, timeout=10)
        except Exception as exc:  # noqa: BLE001
            res = exc
        mikrotik.record(db, j, res)
    return len(jobs)


# --------------------------------------------------------------------- coleta --


def test_pull_encrypts_pins_host_key_and_verifies(db, rb, ros, keyring, keys):  # noqa: F811
    assert pull(db) == 1
    assert ros.commands == ["/export show-sensitive"]
    b = db.query(Backup).one()
    assert b.status == BackupStatus.ok, b.error_message
    comp = b.components[0]
    assert comp.name == "rb-core.rsc" and comp.file_name.endswith(".gpg")
    assert "coletado via SSH" in comp.message
    stored = Path(settings.storage_path) / b.storage_path / comp.file_name
    assert b"RouterOS" not in stored.read_bytes()  # só o cifrado no disco
    db.refresh(rb)
    assert rb.pull_host_key and rb.pull_host_key.startswith("ecdsa-sha2-")
    assert rb.pull_error is None and rb.last_status == "ok"
    assert rb.pull_next_at > utcnow() + timedelta(hours=23)
    verify.verify_backup(db, b, keyring)
    assert b.verify_status == VerifyStatus.ok, b.verify_message

    # não vence de novo antes do intervalo
    assert pull(db) == 0
    # coletar agora; a data do cabeçalho muda, o resto não => idêntica ao anterior
    ros.export = ROS7_EXPORT.replace(b"03:00:01", b"04:10:00")
    rb.pull_next_at = None
    db.commit()
    assert pull(db) == 1
    latest = db.query(Backup).order_by(Backup.id.desc()).first()
    assert "idêntica" in latest.components[0].message


def test_pull_routeros6_falls_back_to_plain_export(db, rb, ros, keyring, keys):  # noqa: F811
    ros.v6, ros.export = True, ROS6_EXPORT
    pull(db)
    assert ros.commands == ["/export show-sensitive", "/export"]
    b = db.query(Backup).one()
    assert b.status == BackupStatus.ok, b.error_message
    assert b.manifest["remote_path"] == "/export"


def test_pull_wrong_password_records_failure(db, rb, ros, keyring, keys):  # noqa: F811
    cred = db.get(DeviceCredential, rb.pull_credential_id)
    cred.password_enc = crypto.encrypt("senha-errada")
    db.commit()
    pull(db)
    b = db.query(Backup).one()
    assert b.status == BackupStatus.failed and b.storage_path is None
    assert b.verify_status == VerifyStatus.skipped
    assert "recusados" in b.error_message
    db.refresh(rb)
    assert rb.last_status == "failed" and "recusados" in rb.pull_error
    assert rb.pull_host_key is None  # só fixa depois de uma coleta boa


def test_pull_host_key_change_blocks(db, rb, ros, keyring, keys):  # noqa: F811
    pull(db)
    ros.new_host_key()
    ros.commands.clear()
    rb.pull_next_at = None
    db.commit()
    pull(db)
    assert ros.commands == []  # nem autenticou: a senha não foi entregue
    db.refresh(rb)
    assert "chave de host SSH mudou" in rb.pull_error
    assert db.query(Backup).order_by(Backup.id.desc()).first().status == BackupStatus.failed


def test_pull_unreachable(db, rb, ros, keyring, keys):  # noqa: F811
    ros.close()
    pull(db)
    db.refresh(rb)
    assert "sem conexão" in rb.pull_error or "erro" in rb.pull_error


def test_inactive_device_not_pulled(db, rb, ros):
    rb.is_active = False
    db.commit()
    assert mikrotik.claim_due(db) == []


# ------------------------------------------------------------------------ API --


def test_api_credentials_and_mikrotik_hosts(auth_client, isolated_paths):
    assert auth_client.post("/api/device-credentials", json={
        "name": "x", "username": USER, "password": 'com"aspas'}).status_code == 422
    r = auth_client.post("/api/device-credentials", json={
        "name": "Padrão", "username": USER, "password": PASSWORD, "port": 2200})
    assert r.status_code == 201, r.text
    cred = r.json()
    assert "password" not in cred and "password_enc" not in cred
    assert auth_client.post("/api/device-credentials", json={
        "name": "Padrão", "username": "outro", "password": PASSWORD}).status_code == 409

    base = {"name": "RB Core", "kind": "network", "vendor": "mikrotik", "mgmt_ip": "10.0.0.1",
            "expected_interval_hours": 24}
    assert auth_client.post("/api/clients", json=base | {"slug": "rb-core", "protocol": "ftp",
                                                         "pull_credential_id": cred["id"]}).status_code == 422
    no_cred = base | {"slug": "rb-core", "protocol": "ssh"}
    assert auth_client.post("/api/clients", json=no_cred).status_code == 422
    assert auth_client.post("/api/clients", json=base | {"slug": "rb-core", "protocol": "ssh",
                                                         "pull_credential_id": cred["id"],
                                                         "expected_interval_hours": 0}).status_code == 422
    # SSH só para MikroTik
    assert auth_client.post("/api/clients", json=base | {"slug": "sw", "vendor": "huawei", "protocol": "ssh",
                                                         "mgmt_ip": "10.0.0.9"}).status_code == 422
    r = auth_client.post("/api/clients", json=base | {"slug": "rb-core", "protocol": "ssh",
                                                      "pull_credential_id": cred["id"]})
    assert r.status_code == 201, r.text
    dev = r.json()
    assert dev["pull_credential_id"] == cred["id"] and dev["pull_port"] is None

    # o IP do MikroTik NÃO ganha acesso aos receptores FTP/TFTP
    allow = json.loads((Path(settings.receivers_shared_dir) / receivers.ALLOWLIST_FILE).read_text())
    assert all(d["ip"] != "10.0.0.1" for d in allow["devices"])

    r = auth_client.get("/api/clients", params={"vendor": "mikrotik"})
    assert [c["slug"] for c in r.json()] == ["rb-core"]
    assert auth_client.get("/api/device-credentials").json()[0]["device_count"] == 1

    r = auth_client.patch(f"/api/clients/{dev['id']}", json={"pull_port": 8022})
    assert r.status_code == 200 and r.json()["pull_port"] == 8022
    r = auth_client.patch(f"/api/clients/{dev['id']}", json={"pull_port": None})
    assert r.json()["pull_port"] is None

    r = auth_client.post(f"/api/clients/{dev['id']}/pull-now")
    assert r.status_code == 200 and r.json()["pull_next_at"] is not None
    assert auth_client.post(f"/api/clients/{dev['id']}/accept-host-key").status_code == 200

    # credencial em uso não pode ser excluída
    assert auth_client.delete(f"/api/device-credentials/{cred['id']}").status_code == 409
    assert auth_client.patch(f"/api/device-credentials/{cred['id']}",
                             json={"password": "Outra-senha-2"}).status_code == 200
    assert auth_client.delete(f"/api/clients/{dev['id']}").status_code == 204
    assert auth_client.delete(f"/api/device-credentials/{cred['id']}").status_code == 204
