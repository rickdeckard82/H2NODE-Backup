"""Servidor de firmwares (página FTP Firmwares): download por TFTP (RRQ) e FTP só leitura,
sem abrir os backups, e a API do painel."""

import ftplib
import io
import json
import socket
import struct
import threading
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.security import hash_password
from app.receivers import ftp as ftp_recv
from app.receivers import tftp as tftp_recv
from app.services import firmware, receivers
from tests.test_network import FTP_PASS, FTP_USER, HUAWEI_CFG, tftp_put, wait_ready

FW_USER, FW_PASS = "firmware", "Firmware-teste-01"
IMAGE = bytes(range(256)) * 40 + b"fim"  # vários blocos, não múltiplo do bloco
FTP_LOOP = {"timeout": 0.2, "handle_exit": False}


def write_allowlist(devices: list[dict] | None = None, accounts: dict[str, str] | None = None,
                    fw: dict | None = None) -> receivers.Allowlist:
    path = Path(settings.receivers_shared_dir) / receivers.ALLOWLIST_FILE
    path.write_text(json.dumps({
        "devices": devices or [],
        "ftp_accounts": [{"username": u, "password_hash": h} for u, h in (accounts or {}).items()],
        "managers": [],
        "firmware": fw,
    }))
    return receivers.Allowlist(path)


def put_firmware(name: str, data: bytes) -> Path:
    firmware.ensure_layout()
    p = firmware.files_dir() / name
    p.write_bytes(data)
    return p


def tftp_get(port: int, name: str, blksize: int | None = 1024,
             tsize: bool = False) -> tuple[bytes | None, bytes]:
    """Cliente TFTP mínimo de leitura: (mensagem de erro ou None, dados)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    opts = b""
    if blksize:
        opts += b"blksize\0" + str(blksize).encode() + b"\0"
    if tsize:
        opts += b"tsize\0" + b"0\0"
    s.sendto(struct.pack("!H", 1) + name.encode() + b"\0octet\0" + opts, ("127.0.0.1", port))
    out = bytearray()
    size = 512
    expected = 1
    try:
        while True:
            pkt, srv = s.recvfrom(70000)
            op = struct.unpack("!H", pkt[:2])[0]
            if op == 5:
                return pkt[4:-1], bytes(out)
            if op == 6:  # OACK
                fields = pkt[2:].split(b"\0")[:-1]
                o = {fields[i].decode(): fields[i + 1].decode() for i in range(0, len(fields), 2)}
                size = int(o.get("blksize", 512))
                if tsize:
                    assert int(o["tsize"]) == len(IMAGE)
                s.sendto(struct.pack("!HH", 4, 0), srv)
                continue
            assert op == 3
            block = struct.unpack("!H", pkt[2:4])[0]
            assert block == expected
            out += pkt[4:]
            s.sendto(struct.pack("!HH", 4, block), srv)
            expected = (expected + 1) % 65536
            if len(pkt) - 4 < size:
                return None, bytes(out)
    finally:
        s.close()


@pytest.fixture
def tftp_fw():
    allow = write_allowlist(
        [{"slug": "dm4380", "ip": "127.0.0.1", "protocol": "tftp", "vendor": "datacom"}],
        fw={"ftp_user": None, "password_hash": None, "networks": ["127.0.0.0/8"], "ips": []},
    )
    srv = tftp_recv.TftpServer("127.0.0.1", 0, allow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.stop()


def test_tftp_serves_firmware(tftp_fw):
    put_firmware("S5720-V200R011.cc", IMAGE)
    assert tftp_get(tftp_fw.port, "S5720-V200R011.cc") == (None, IMAGE)
    # caminho é só rótulo; maiúsculas não importam se só um arquivo combina; tsize volta o tamanho
    assert tftp_get(tftp_fw.port, "/firmware/s5720-v200r011.CC", blksize=None, tsize=True) == (None, IMAGE)


def test_tftp_firmware_exact_multiple_ends_with_empty_block(tftp_fw):
    put_firmware("img.bin", b"x" * 1024)
    assert tftp_get(tftp_fw.port, "img.bin", blksize=512) == (None, b"x" * 1024)


def test_tftp_firmware_not_found_and_never_reads_backups(tftp_fw):
    firmware.ensure_layout()
    # um backup recebido continua inacessível, por qualquer caminho
    assert tftp_put(tftp_fw.port, "config.txt", b"hostname x\n") is None
    stored = wait_ready("dm4380")[0]
    for name in ("config.txt", stored.name, f"../../netin/dm4380/{stored.name}", "../files/x"):
        err, data = tftp_get(tftp_fw.port, name)
        assert err is not None and data == b""


def test_tftp_firmware_refused_outside_allowed_networks():
    allow = write_allowlist(fw={"ftp_user": None, "password_hash": None, "networks": ["192.0.2.0/24"],
                                "ips": []})
    srv = tftp_recv.TftpServer("127.0.0.1", 0, allow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        put_firmware("img.bin", IMAGE)
        err, _ = tftp_get(srv.port, "img.bin")
        assert err and b"permitida" in err
    finally:
        srv.stop()


def test_allowlist_firmware_ips_and_networks():
    allow = write_allowlist(fw={"ftp_user": "fw", "password_hash": "h", "networks": ["10.1.0.0/16", "lixo"],
                                "ips": ["192.0.2.7"]})
    assert allow.firmware_allows("10.1.2.3") and allow.firmware_allows("::ffff:10.1.2.3")
    assert allow.firmware_allows("192.0.2.7")
    assert not allow.firmware_allows("10.2.0.1") and not allow.firmware_allows("2001:db8::1")
    assert allow.is_firmware_user("fw") and not allow.is_firmware_user("juniper")
    off = write_allowlist(fw=None)
    assert not off.firmware_allows("10.1.2.3") and not off.is_firmware_user("fw")


# --------------------------------------------------------------------- FTP --


@pytest.fixture
def ftp_fw():
    allow = write_allowlist(
        [{"slug": "mx1", "ip": "127.0.0.1", "protocol": "ftp", "vendor": "juniper"}],
        {FTP_USER: hash_password(FTP_PASS)},
        fw={"ftp_user": FW_USER, "password_hash": hash_password(FW_PASS), "networks": ["127.0.0.1/32"],
            "ips": []},
    )
    srv = ftp_recv.build_server("127.0.0.1", 0, allow)
    threading.Thread(target=srv.serve_forever, kwargs=FTP_LOOP, daemon=True).start()
    yield srv
    srv.close_all()


def ftp_login(srv, user: str, pw: str) -> ftplib.FTP:
    f = ftplib.FTP()
    f.connect("127.0.0.1", srv.address[1], timeout=5)
    f.login(user, pw)
    return f


def test_ftp_firmware_lists_and_downloads(ftp_fw):
    put_firmware("S5720-V200R011.cc", IMAGE)
    f = ftp_login(ftp_fw, FW_USER, FW_PASS)
    assert f.nlst() == ["S5720-V200R011.cc"]
    buf = io.BytesIO()
    f.retrbinary("RETR S5720-V200R011.cc", buf.write)
    assert buf.getvalue() == IMAGE
    f.quit()


def test_ftp_firmware_is_read_only(ftp_fw):
    put_firmware("img.bin", IMAGE)
    f = ftp_login(ftp_fw, FW_USER, FW_PASS)
    with pytest.raises(ftplib.error_perm):
        f.storbinary("STOR novo.bin", io.BytesIO(b"x"))
    with pytest.raises(ftplib.error_perm):
        f.storbinary("APPE img.bin", io.BytesIO(b"x"))
    with pytest.raises(ftplib.error_perm):
        f.delete("img.bin")
    with pytest.raises(ftplib.error_perm):
        f.mkd("pasta")
    with pytest.raises(ftplib.error_perm):
        f.sendcmd("RNFR img.bin")
    with pytest.raises(ftplib.error_perm):
        f.cwd("nao-existe")  # e a pasta não é criada (o envio de backup cria; o firmware não)
    with pytest.raises(ftplib.error_perm):
        f.retrbinary("RETR ../../netin/x", lambda b: None)
    f.quit()
    assert sorted(p.name for p in firmware.files_dir().iterdir()) == ["img.bin"]
    assert (firmware.files_dir() / "img.bin").read_bytes() == IMAGE


def test_ftp_backup_account_still_write_only_and_cannot_see_firmware(ftp_fw):
    put_firmware("img.bin", IMAGE)
    f = ftp_login(ftp_fw, FTP_USER, FTP_PASS)
    assert f.nlst() == []  # sessão de backup: pasta própria e vazia
    with pytest.raises(ftplib.error_perm):
        f.retrbinary("RETR img.bin", lambda b: None)
    f.storbinary("STOR vrpcfg.cfg", io.BytesIO(HUAWEI_CFG))
    f.quit()
    assert len(wait_ready("mx1")) == 1


def test_ftp_firmware_wrong_password_or_ip(ftp_fw):
    with pytest.raises(ftplib.error_perm):
        ftp_login(ftp_fw, FW_USER, "errada")
    # IP fora das redes de firmware e sem cadastro: cai antes do login
    ftp_fw.allowlist.by_ip = {}
    ftp_fw.allowlist.fw_nets = []
    ftp_fw.allowlist.refresh = lambda: None
    with pytest.raises((ftplib.error_temp, EOFError, ConnectionError)):
        ftp_login(ftp_fw, FW_USER, FW_PASS)


def test_ftp_firmware_only_ip_cannot_use_backup_account():
    # IP liberado só para firmware (sem cadastro de equipamento): a conta de backup não entra
    allow = write_allowlist(accounts={FTP_USER: hash_password(FTP_PASS)},
                            fw={"ftp_user": FW_USER, "password_hash": hash_password(FW_PASS),
                                "networks": ["127.0.0.0/8"], "ips": []})
    firmware.ensure_layout()
    srv = ftp_recv.build_server("127.0.0.1", 0, allow)
    threading.Thread(target=srv.serve_forever, kwargs=FTP_LOOP, daemon=True).start()
    try:
        with pytest.raises(ftplib.error_perm):
            ftp_login(srv, FTP_USER, FTP_PASS)
        ftp_login(srv, FW_USER, FW_PASS).quit()
    finally:
        srv.close_all()


# --------------------------------------------------------------------- API --


def test_api_firmware_settings_and_receivers_json(auth_client, isolated_paths):
    r = auth_client.get("/api/firmware")
    assert r.status_code == 200 and r.json()["settings"]["enabled"] is False
    allow_path = isolated_paths / "netcfg" / receivers.ALLOWLIST_FILE

    body = {"enabled": True, "ftp_username": "firmware", "allowed_networks": ["10.0.0.0/8"]}
    assert auth_client.put("/api/firmware/settings", json=body).status_code == 422  # sem senha
    assert auth_client.put("/api/firmware/settings",
                           json=body | {"ftp_password": "Senha-fw-01",
                                        "allowed_networks": ["0.0.0.0/0"]}).status_code == 422
    assert auth_client.put("/api/firmware/settings",
                           json=body | {"ftp_password": "Senha-fw-01",
                                        "allowed_networks": ["não é ip"]}).status_code == 422
    r = auth_client.put("/api/firmware/settings",
                        json=body | {"ftp_password": "Senha-fw-01",
                                     "allowed_networks": ["10.1.2.3", " ", "10.0.0.0/8"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"enabled": True, "ftp_username": "firmware", "has_password": True,
                        "allowed_networks": ["10.1.2.3/32", "10.0.0.0/8"], "include_devices": True}

    # equipamento cadastrado entra na lista de firmware (include_devices)
    assert auth_client.post("/api/clients", json={
        "slug": "sw1", "name": "SW1", "kind": "network", "vendor": "datacom", "protocol": "tftp",
        "mgmt_ip": "192.0.2.20", "expected_interval_hours": 0}).status_code == 201
    allow = json.loads(allow_path.read_text())
    assert allow["firmware"]["ftp_user"] == "firmware" and allow["firmware"]["ips"] == ["192.0.2.20"]
    assert allow["firmware"]["networks"] == ["10.1.2.3/32", "10.0.0.0/8"]
    assert "Senha-fw-01" not in allow_path.read_text()

    # login de firmware e Contas FTP não podem ter o mesmo nome
    r = auth_client.post("/api/ftp-accounts", json={"username": "firmware", "password": "Senha-forte-1"})
    assert r.status_code == 409
    assert auth_client.post("/api/ftp-accounts", json={"username": "huawei",
                                                       "password": "Senha-forte-1"}).status_code == 201
    assert auth_client.put("/api/firmware/settings",
                           json=body | {"ftp_username": "huawei",
                                        "ftp_password": "Senha-fw-01"}).status_code == 409

    # trocar o usuário sem senha nova exige a senha
    assert auth_client.put("/api/firmware/settings", json=body | {"ftp_username": "fw2"}).status_code == 422

    # desligado: some do receivers.json
    r = auth_client.put("/api/firmware/settings", json=body | {"enabled": False})
    assert r.status_code == 200 and r.json()["has_password"] is True
    assert json.loads(allow_path.read_text())["firmware"] is None


def test_api_firmware_upload_list_delete(auth_client):
    r = auth_client.put("/api/firmware/files/S5720-V200R011.cc", content=IMAGE)
    assert r.status_code == 200, r.text
    assert r.json()["size"] == len(IMAGE)
    assert (firmware.files_dir() / "S5720-V200R011.cc").read_bytes() == IMAGE
    assert list(firmware.tmp_dir().iterdir()) == []
    files = auth_client.get("/api/firmware").json()["files"]
    assert [f["name"] for f in files] == ["S5720-V200R011.cc"]
    # substitui
    assert auth_client.put("/api/firmware/files/S5720-V200R011.cc", content=b"novo").json()["size"] == 4

    for bad in (".oculto", "a b.bin", "..", "x%2Fy.bin"):
        assert auth_client.put(f"/api/firmware/files/{bad}", content=b"x").status_code in (404, 405, 422)
    assert auth_client.put("/api/firmware/files/vazio.bin", content=b"").status_code == 422

    assert auth_client.delete("/api/firmware/files/S5720-V200R011.cc").status_code == 204
    assert auth_client.delete("/api/firmware/files/S5720-V200R011.cc").status_code == 404
    assert auth_client.get("/api/firmware").json()["files"] == []


def test_api_firmware_upload_too_large(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "firmware_max_mb", 0)
    assert auth_client.put("/api/firmware/files/grande.bin", content=b"x").status_code == 413
    assert list(firmware.tmp_dir().iterdir()) == []


# ------------------------------------------------------- conexões ativas --


def _wait_status(proto: str, n: int) -> list[dict]:
    import time

    for _ in range(60):
        online, _, sessions = firmware.read_status(proto)
        if online and len(sessions) == n:
            return sessions
        time.sleep(0.05)
    return firmware.read_status(proto)[2]


def test_ftp_firmware_session_is_published_while_connected(ftp_fw):
    put_firmware("img.bin", IMAGE)
    f = ftp_login(ftp_fw, FW_USER, FW_PASS)
    sessions = _wait_status("ftp", 1)
    assert len(sessions) == 1 and sessions[0]["user"] == FW_USER and sessions[0]["ip"] == "127.0.0.1"
    f.quit()
    assert _wait_status("ftp", 0) == []
    # sessão de backup não aparece no monitor de firmware
    b = ftp_login(ftp_fw, FTP_USER, FTP_PASS)
    assert _wait_status("ftp", 0) == []
    b.quit()


def test_tftp_read_is_published_and_cleared(tftp_fw):
    put_firmware("img.bin", IMAGE)
    assert tftp_get(tftp_fw.port, "img.bin") == (None, IMAGE)
    assert _wait_status("tftp", 0) == []
    assert firmware.read_status("tftp")[0] is True


def test_api_connections_reads_status_and_detects_stale(auth_client, monkeypatch):
    import time

    firmware.StatusPublisher("ftp").publish([{"id": "ftp-1", "ip": "192.0.2.9", "user": "firmware",
                                               "since": time.time() - 30, "file": "img.bin",
                                               "sent": 100, "size": 1000}])
    r = auth_client.get("/api/firmware/connections").json()
    assert r["receivers"]["ftp"]["online"] is True and r["receivers"]["tftp"]["online"] is False
    assert [(c["protocol"], c["ip"], c["file"], c["sent"], c["size"]) for c in r["connections"]] == [
        ("ftp", "192.0.2.9", "img.bin", 100, 1000)]
    monkeypatch.setattr(firmware, "STATUS_STALE", -1)
    r = auth_client.get("/api/firmware/connections").json()
    assert r["receivers"]["ftp"]["online"] is False and r["connections"] == []


def test_api_firmware_comment(auth_client):
    c = "/api/firmware/files/img.bin/info"
    assert auth_client.put(c, json={"comment": "x"}).status_code == 404
    auth_client.put("/api/firmware/files/img.bin", content=IMAGE)
    r = auth_client.put(c, json={"comment": "  RP1900\n  OLT   GPON  "})
    assert r.status_code == 200 and r.json()["comment"] == "RP1900 OLT GPON"
    assert auth_client.put(c, json={"comment": "x" * 201}).status_code == 422
    # substituir o arquivo mantém o comentário; excluir apaga
    r = auth_client.put("/api/firmware/files/img.bin", content=b"novo")
    assert r.json()["comment"] == "RP1900 OLT GPON"
    assert auth_client.get("/api/firmware").json()["files"][0]["comment"] == "RP1900 OLT GPON"
    assert auth_client.put(c, json={"comment": " "}).json()["comment"] is None
    auth_client.put(c, json={"comment": "antigo"})
    assert auth_client.delete("/api/firmware/files/img.bin").status_code == 204
    auth_client.put("/api/firmware/files/img.bin", content=IMAGE)
    assert auth_client.get("/api/firmware").json()["files"][0]["comment"] is None


def test_api_firmware_vendor(auth_client):
    auth_client.put("/api/firmware/files/a.bin", content=IMAGE)
    c = "/api/firmware/files/a.bin/info"
    assert auth_client.put(c, json={"vendor": "files"}).status_code == 422  # não é fabricante de firmware
    r = auth_client.put(c, json={"vendor": "fiberhome"}).json()
    assert r["vendor"] == "fiberhome" and r["comment"] is None
    r = auth_client.put(c, json={"vendor": "fiberhome", "comment": "GC8B"}).json()
    assert (r["vendor"], r["comment"]) == ("fiberhome", "GC8B")
    assert auth_client.get("/api/firmware").json()["files"][0]["vendor"] == "fiberhome"
    r = auth_client.put(c, json={"comment": ""}).json()
    assert r["vendor"] is None and r["comment"] is None
