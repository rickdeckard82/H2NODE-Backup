import base64
import struct

from app.core.config import settings
from app.services import sshkeys

ED_KEY = "ssh-ed25519 " + base64.b64encode(
    struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + b"\x01" * 32
).decode() + " root@web01"


def test_parse_key_and_fingerprint():
    line, fp = sshkeys.parse_public_key(ED_KEY)
    assert line.startswith("ssh-ed25519 AAAA")
    assert "root@web01" not in line
    assert fp.startswith("SHA256:")


def test_reject_bad_keys():
    import pytest

    for bad in [
        "",
        'command="sh" ' + ED_KEY,                    # opções embutidas
        "ssh-ed25519 !!!notbase64",
        "ssh-dss AAAAB3NzaC1kc3MAAACBAP",             # tipo não aceito
        ED_KEY.replace("ssh-ed25519 AAAA", "ssh-rsa AAAA", 1),  # tipo não confere
        ED_KEY + "\n" + ED_KEY,
    ]:
        with pytest.raises(sshkeys.InvalidSshKey):
            sshkeys.parse_public_key(bad)


def test_create_client_writes_authorized_keys(auth_client, isolated_paths):
    r = auth_client.post("/api/clients", json={"slug": "web01", "name": "Web 01", "ssh_public_key": ED_KEY})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ssh_key_fingerprint"].startswith("SHA256:")
    assert body["health"] == "never"

    ak = (isolated_paths / "ssh" / "authorized_keys").read_text()
    assert f'restrict,command="/usr/bin/rrsync -wo -no-del {settings.storage_path}/incoming/web01"' in ak
    assert (isolated_paths / "data" / "incoming" / "web01").is_dir()

    # desativar remove a linha
    auth_client.patch(f"/api/clients/{body['id']}", json={"is_active": False})
    ak = (isolated_paths / "ssh" / "authorized_keys").read_text()
    assert "web01" not in ak.split("\n", 1)[1]


def test_slug_validation_and_duplicates(auth_client):
    assert auth_client.post("/api/clients", json={"slug": "../etc", "name": "x"}).status_code == 422
    assert auth_client.post("/api/clients", json={"slug": "Web01", "name": "x"}).status_code == 422
    assert auth_client.post("/api/clients", json={"slug": "web01", "name": "x"}).status_code == 201
    assert auth_client.post("/api/clients", json={"slug": "web01", "name": "y"}).status_code == 409


def test_same_key_two_clients_rejected(auth_client):
    r = auth_client.post("/api/clients", json={"slug": "a01", "name": "a", "ssh_public_key": ED_KEY})
    assert r.status_code == 201
    r = auth_client.post("/api/clients", json={"slug": "b01", "name": "b", "ssh_public_key": ED_KEY})
    assert r.status_code == 409


def test_agent_config(auth_client):
    cid = auth_client.post("/api/clients", json={"slug": "db01", "name": "Banco"}).json()["id"]
    r = auth_client.get(f"/api/clients/{cid}/agent-config")
    assert r.status_code == 200
    assert 'CLIENT_ID="db01"' in r.json()["content"]
    assert r.json()["public_key_available"] is False
