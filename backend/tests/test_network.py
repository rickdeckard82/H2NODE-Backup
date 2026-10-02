"""Equipamentos de rede: receptores TFTP/FTP reais (sockets locais), validação
por fabricante, recepção com cifragem GPG e API."""

import ftplib
import gzip
import io
import json
import socket
import struct
import threading
import zipfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.security import hash_password
from app.models import Backup, BackupStatus, Client, VerifyStatus
from app.receivers import ftp as ftp_recv
from app.receivers import tftp as tftp_recv
from app.services import netconfig, netingest, receivers, verify
from tests.test_pipeline import keyring, keys  # noqa: F401  (fixtures)

HUAWEI_CFG = b"#\n sysname SW-CORE\n#\ninterface Vlanif10\n ip address 192.0.2.15 255.255.255.0\n#\nreturn\n"
JUNOS_CFG = b"## Last commit: 2026-10-01\nversion 23.4R1;\nsystem {\n    host-name mx1;\n}\ninterfaces {\n}\n"
DMOS_CFG = b"hostname DM4380MP\naaa user admin\ndot1q\n vlan 10\n!\ninterface l3 mgmt\n"

FTP_USER, FTP_PASS = "juniper", "Senha-teste-01"


# ------------------------------------------------------------------ netconfig --


def test_netconfig_vendor_checks():
    assert netconfig.check(HUAWEI_CFG, "huawei").ok
    assert not netconfig.check(HUAWEI_CFG.replace(b"return\n", b""), "huawei").ok
    assert netconfig.check(gzip.compress(JUNOS_CFG), "juniper").ok
    assert netconfig.check(gzip.compress(JUNOS_CFG), "juniper").format == "gzip"
    assert not netconfig.check(gzip.compress(JUNOS_CFG)[:-10], "juniper").ok  # gzip truncado
    assert not netconfig.check(JUNOS_CFG.replace(b"}\ninterfaces", b"\ninterfaces"), "juniper").ok
    assert netconfig.check(DMOS_CFG, "datacom").ok
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("vrpcfg.cfg", HUAWEI_CFG)
    assert netconfig.check(buf.getvalue(), "huawei").ok
    assert not netconfig.check(b"", "generic").ok
    assert not netconfig.check(b"\x00\x01\x02" * 100, "generic").ok


# --------------------------------------------------------------- receptores --


def write_allowlist(devices: list[dict], accounts: dict[str, str] | None = None) -> receivers.Allowlist:
    path = Path(settings.receivers_shared_dir) / receivers.ALLOWLIST_FILE
    path.write_text(json.dumps({
        "devices": devices,
        "ftp_accounts": [{"username": u, "password_hash": h} for u, h in (accounts or {}).items()],
    }))
    return receivers.Allowlist(path)


def tftp_put(port: int, name: str, data: bytes, blksize: int | None = 1024) -> bytes | None:
    """Cliente TFTP mínimo. Devolve a mensagem de erro do servidor, se houver."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    opts = b"blksize\0" + str(blksize).encode() + b"\0" if blksize else b""
    s.sendto(struct.pack("!H", 2) + name.encode() + b"\0octet\0" + opts, ("127.0.0.1", port))
    pkt, srv = s.recvfrom(1024)
    op = struct.unpack("!H", pkt[:2])[0]
    if op == 5:
        return pkt[4:-1]
    size = blksize if (op == 6 and blksize) else 512
    block = 1
    for off in range(0, len(data) + 1, size):
        chunk = data[off:off + size]
        s.sendto(struct.pack("!HH", 3, block) + chunk, srv)
        ack, _ = s.recvfrom(1024)
        assert struct.unpack("!HH", ack[:4]) == (4, block)
        block += 1
        if len(chunk) < size:
            break
    s.close()
    return None


@pytest.fixture
def tftp_server():
    allow = write_allowlist([{"slug": "dm4380", "ip": "127.0.0.1", "protocol": "tftp", "vendor": "datacom"}])
    srv = tftp_recv.TftpServer("127.0.0.1", 0, allow)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.stop()


def ready_files(slug: str) -> list[Path]:
    d = receivers.netin() / slug
    return sorted(p for p in d.glob("*") if not p.name.endswith(receivers.META_SUFFIX)) if d.is_dir() else []


def wait_ready(slug: str, n: int = 1) -> list[Path]:
    import time

    for _ in range(50):
        files = ready_files(slug)
        if len(files) >= n and all(Path(str(f) + receivers.META_SUFFIX).exists() for f in files):
            return files
        time.sleep(0.05)
    return ready_files(slug)


def test_tftp_receives_write(tftp_server):
    data = DMOS_CFG * 300  # vários blocos
    assert tftp_put(tftp_server.port, "DM4380MP/config.txt", data) is None
    files = wait_ready("dm4380")
    assert len(files) == 1 and files[0].read_bytes() == data
    meta = json.loads(Path(str(files[0]) + receivers.META_SUFFIX).read_text())
    assert meta["protocol"] == "tftp" and meta["remote_path"] == "DM4380MP/config.txt"
    assert files[0].name.endswith("__DM4380MP_config.txt")


def test_tftp_default_blksize_and_exact_multiple(tftp_server):
    data = b"x" * 1024  # múltiplo exato de 512: termina com DATA vazio
    assert tftp_put(tftp_server.port, "c.txt", data, blksize=None) is None
    assert wait_ready("dm4380")[0].read_bytes() == data


def test_tftp_refuses_read_and_unknown_ip(tftp_server):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    s.sendto(struct.pack("!H", 1) + b"config.txt\0octet\0", ("127.0.0.1", tftp_server.port))
    pkt, _ = s.recvfrom(1024)
    assert struct.unpack("!HH", pkt[:4]) == (5, 2)
    tftp_server.allowlist.path.write_text(json.dumps({"devices": [], "ftp_accounts": []}))
    import os
    import time
    os.utime(tftp_server.allowlist.path, (time.time() + 5, time.time() + 5))
    assert b"autorizado" in tftp_put(tftp_server.port, "x.txt", b"abc")


@pytest.fixture
def ftp_server():
    allow = write_allowlist(
        [{"slug": "mx1", "ip": "127.0.0.1", "protocol": "ftp", "vendor": "juniper"}],
        {FTP_USER: hash_password(FTP_PASS)},
    )
    srv = ftp_recv.build_server("127.0.0.1", 0, allow)
    t = threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2, "handle_exit": False}, daemon=True)
    t.start()
    yield srv
    srv.close_all()


def ftp_connect(srv) -> ftplib.FTP:
    f = ftplib.FTP()
    f.connect("127.0.0.1", srv.address[1], timeout=5)
    return f


def test_ftp_upload_juniper_root_and_huawei_path(ftp_server):
    f = ftp_connect(ftp_server)
    f.login(FTP_USER, FTP_PASS)
    gz = gzip.compress(JUNOS_CFG)
    f.storbinary("STOR mx1_juniper.conf.gz_20261001_120000", io.BytesIO(gz))
    # Huawei: caminho com pasta que não existe ("./<ip>/arquivo")
    f.storbinary("STOR ./192.0.2.15/vrpcfg.cfg", io.BytesIO(HUAWEI_CFG))
    with pytest.raises(ftplib.error_perm):
        f.retrbinary("RETR mx1_juniper.conf.gz_20261001_120000", lambda b: None)
    with pytest.raises(ftplib.error_perm):
        f.delete("qualquer")
    f.quit()
    files = wait_ready("mx1", 2)
    names = sorted(p.name.split("__", 1)[1] for p in files)
    assert names == ["192.0.2.15_vrpcfg.cfg", "mx1_juniper.conf.gz_20261001_120000"]
    assert any(p.read_bytes() == gz for p in files)


def test_ftp_wrong_password(ftp_server):
    f = ftp_connect(ftp_server)
    with pytest.raises(ftplib.error_perm):
        f.login(FTP_USER, "errada")
    f.close()


def test_ftp_unknown_ip_is_dropped(ftp_server):
    ftp_server.allowlist.by_ip = {}
    ftp_server.allowlist.refresh = lambda: None  # congela a lista vazia
    with pytest.raises((ftplib.error_temp, EOFError, ConnectionError)):
        f = ftp_connect(ftp_server)
        f.login(FTP_USER, FTP_PASS)


# ------------------------------------------------------- recepção no worker --


@pytest.fixture
def mx1(db):
    c = Client(slug="mx1", name="MX core", kind="network", vendor="juniper",
               mgmt_ip="192.0.2.1", protocol="ftp", expected_interval_hours=0)
    db.add(c)
    db.commit()
    return c


def drop_upload(slug: str, name: str, data: bytes, protocol: str = "ftp") -> None:
    tmp = receivers.netin() / ".tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / "up"
    src.write_bytes(data)
    receivers.finalize(src, receivers.Device(slug, "192.0.2.1", protocol, None),
                       protocol=protocol, remote_path=name, size=len(data))


def test_netingest_encrypts_and_verifies(db, mx1, keyring, keys):  # noqa: F811
    gz = gzip.compress(JUNOS_CFG)
    drop_upload("mx1", "mx1_juniper.conf.gz_20261001_120000", gz)
    assert netingest.scan(db) == 1
    assert not any(receivers.netin().joinpath("mx1").iterdir())  # original em claro apagado
    b = db.query(Backup).one()
    assert b.status == BackupStatus.ok
    comp = b.components[0]
    assert comp.kind == "config" and comp.file_name.endswith(".gpg")
    stored = Path(settings.storage_path) / b.storage_path / comp.file_name
    assert stored.read_bytes()[:1] != b"\x1f"  # cifrado, não é o gzip original
    assert b"system {" not in stored.read_bytes()
    verify.verify_backup(db, b, keyring)
    assert b.verify_status == VerifyStatus.ok, b.verify_message
    assert "linhas" in comp.verify_message

    # mesmo conteúdo de novo => marcado como idêntico
    drop_upload("mx1", "mx1_juniper.conf.gz_20261001_130000", gz)
    netingest.scan(db)
    latest = db.query(Backup).order_by(Backup.id.desc()).first()
    assert "idêntica" in latest.components[0].message


def test_netingest_invalid_config_is_failed(db, mx1, keyring, keys):  # noqa: F811
    drop_upload("mx1", "lixo.conf.gz", b"\x1f\x8b\x08\x00quebrado")
    netingest.scan(db)
    b = db.query(Backup).one()
    assert b.status == BackupStatus.failed
    assert "compactado inválido" in b.error_message
    assert mx1.last_status == "failed"


def test_netingest_unknown_device_discarded(db, keyring, keys):  # noqa: F811
    drop_upload("fantasma", "x.cfg", HUAWEI_CFG)
    assert netingest.scan(db) == 0
    assert not list((receivers.netin() / "fantasma").iterdir())


def test_on_demand_device_never_overdue(db, mx1):
    from datetime import timedelta

    from app.core.security import utcnow
    from app.services.health import client_health

    mx1.last_backup_at = utcnow() - timedelta(days=90)
    mx1.last_status = "ok"
    assert client_health(mx1) == "ok"


# ------------------------------------------------------------------------ API --


def test_api_network_device_and_ftp_accounts(auth_client, isolated_paths):
    r = auth_client.post("/api/clients", json={"slug": "sw-core", "name": "SW Core", "kind": "network",
                                               "vendor": "huawei", "protocol": "ftp"})
    assert r.status_code == 422  # sem IP
    body = {"slug": "sw-core", "name": "SW Core", "kind": "network", "vendor": "huawei",
            "protocol": "ftp", "mgmt_ip": "192.0.2.15", "expected_interval_hours": 0,
            "ssh_public_key": "ignorada"}
    r = auth_client.post("/api/clients", json=body)
    assert r.status_code == 201, r.text
    dev = r.json()
    assert dev["kind"] == "network" and dev["ssh_public_key"] is None
    dup = body | {"slug": "sw-2", "vendor": "datacom", "protocol": "tftp"}
    r = auth_client.post("/api/clients", json=dup)
    assert r.status_code == 409  # IP repetido
    assert auth_client.post("/api/clients", json={"slug": "sw-3", "name": "x", "kind": "network",
                                                  "vendor": "datacom", "protocol": "tftp",
                                                  "mgmt_ip": "999.1.1.1"}).status_code == 422

    r = auth_client.post("/api/ftp-accounts", json={"username": "huawei", "password": "a b"})
    assert r.status_code == 422
    r = auth_client.post("/api/ftp-accounts", json={"username": "huawei", "password": "Senha-forte-1"})
    assert r.status_code == 201

    allow = json.loads((isolated_paths / "netcfg" / receivers.ALLOWLIST_FILE).read_text())
    expected = {"slug": "sw-core", "ip": "192.0.2.15", "protocol": "ftp", "vendor": "huawei"}
    assert allow["devices"] == [expected]
    assert allow["ftp_accounts"][0]["username"] == "huawei"
    assert "Senha-forte-1" not in json.dumps(allow)

    cfg = auth_client.get(f"/api/clients/{dev['id']}/device-config").json()
    assert "backup-to-server server" in cfg["commands"] and "user huawei" in cfg["commands"]
    assert "path ./192.0.2.15" in cfg["commands"]
    assert auth_client.get(f"/api/clients/{dev['id']}/agent-config").status_code == 409

    servers = auth_client.get("/api/clients", params={"kind": "server"}).json()
    assert servers == []
