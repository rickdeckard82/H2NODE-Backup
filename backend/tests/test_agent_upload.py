"""Envio por HTTPS (cliente Windows): token, pedaços com retomada, manifesto e o
caminho normal do worker (ingest + verificação com gpg real)."""

import hashlib

from app.models import Backup, BackupStatus, Client, VerifyStatus
from app.services import ingest, verify
from tests.test_pipeline import _encrypt, _tar_gz, keyring, keys  # noqa: F401  (fixtures)

API = "/api/agent/v1"


def _manifest(slug: str, run: str, comps: list[dict], status: str = "success") -> dict:
    return {
        "format": "pulse-backup/1", "client_id": slug, "run_name": run, "agent_version": "win-0.1.0",
        "hostname": "PC-FINANCEIRO", "os": "Windows 11 Pro 24H2",
        "started_at": "2026-10-18T10:00:00Z", "finished_at": "2026-10-18T10:05:00Z",
        "status": status, "components": comps, "errors": [],
    }


def test_https_upload_end_to_end(auth_client, seeded, keys, keyring, tmp_path):  # noqa: F811
    pub = keys["server"][0]
    c = Client(slug="pc-financeiro", name="PC Financeiro")
    seeded.add(c)
    seeded.commit()

    r = auth_client.post(f"/api/clients/{c.id}/upload-token")
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    assert tok.startswith("pbu_") and r.json()["hint"] == tok[-6:]
    assert c.upload_token_hash and tok not in (c.upload_token_hash or "")  # só o hash fica no banco
    H = {"Authorization": f"Bearer {tok}"}

    assert auth_client.get(f"{API}/hello").status_code == 401  # o cookie do painel não vale aqui
    assert auth_client.get(f"{API}/hello", headers={"Authorization": "Bearer pbu_errado"}).status_code == 401
    hello = auth_client.get(f"{API}/hello", headers=H).json()
    assert hello["client_id"] == "pc-financeiro" and "BEGIN PGP PUBLIC KEY" in hello["public_key"]

    run = auth_client.post(f"{API}/runs", headers=H).json()["run_name"]
    plain = _tar_gz({"Documentos/planilha.xlsx": b"x" * 5000, "Documentos/nota.txt": b"ola"})
    data = _encrypt(plain, pub, tmp_path)
    name = "01-files-Documentos.gpg"
    url = f"{API}/runs/{run}/files/{name}"
    half = len(data) // 2

    assert auth_client.put(f"{API}/runs/{run}/files/nota.txt", params={"offset": 0}, headers=H,
                           content=b"x").status_code == 422  # só *.gpg
    assert auth_client.put(url, params={"offset": 0}, headers=H, content=data[:half]).json()["size"] == half
    # pedaço repetido (cliente não sabe se o anterior chegou): 409 e retoma pelo tamanho
    assert auth_client.put(url, params={"offset": 0}, headers=H, content=data[:half]).status_code == 409
    assert auth_client.get(url, headers=H).json()["size"] == half
    assert auth_client.put(url, params={"offset": half}, headers=H, content=data[half:]).json()["size"] == len(data)

    comp = {"kind": "files", "name": r"C:\Users\fin\Documentos", "file": name, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "plain_size": len(plain),
            "plain_sha256": hashlib.sha256(plain).hexdigest(), "status": "ok", "duration_s": 3}
    bad = _manifest("outro-cliente", run, [comp])
    assert auth_client.put(f"{API}/runs/{run}/manifest", headers=H, json=bad).status_code == 422
    assert auth_client.put(f"{API}/runs/{run}/manifest", headers=H,
                           json=_manifest("pc-financeiro", run, [comp])).status_code == 200
    # fechada: nada mais entra
    assert auth_client.put(url, params={"offset": len(data)}, headers=H, content=b"x").status_code == 409

    assert ingest.scan(seeded) == 1
    b = seeded.query(Backup).filter_by(client_id=c.id).one()
    assert b.status == BackupStatus.ok, b.error_message
    assert b.agent_version == "win-0.1.0"
    verify.verify_backup(seeded, b, keyring)
    assert b.verify_status == VerifyStatus.ok, b.verify_message
    seeded.refresh(c)
    assert c.hostname == "PC-FINANCEIRO" and c.os_info.startswith("Windows")

    # execução já recebida: 404
    assert auth_client.get(url, headers=H).status_code == 404

    # token trocado: o antigo para na hora; revogado: nenhum funciona
    new = auth_client.post(f"/api/clients/{c.id}/upload-token").json()["token"]
    assert auth_client.get(f"{API}/hello", headers=H).status_code == 401
    assert auth_client.get(f"{API}/hello", headers={"Authorization": f"Bearer {new}"}).status_code == 200
    assert auth_client.delete(f"/api/clients/{c.id}/upload-token").status_code == 204
    assert auth_client.get(f"{API}/hello", headers={"Authorization": f"Bearer {new}"}).status_code == 401


def test_https_upload_limits(auth_client, seeded, keys, keyring):  # noqa: F811
    c = Client(slug="pc-recepcao", name="PC Recepção")
    seeded.add(c)
    seeded.commit()
    H = {"Authorization": f"Bearer {auth_client.post(f'/api/clients/{c.id}/upload-token').json()['token']}"}

    # no máximo 5 execuções abertas por cliente
    runs = [auth_client.post(f"{API}/runs", headers=H) for _ in range(6)]
    assert [r.status_code for r in runs] == [201] * 5 + [429]

    # execução inexistente / de outro cliente
    assert auth_client.get(f"{API}/runs/20260101T000000Z-abcdef/files/x.gpg", headers=H).status_code == 404
    assert auth_client.get(f"{API}/runs/..%2F..%2Fetc/files/x.gpg", headers=H).status_code == 404

    # cliente inativo: 403
    c.is_active = False
    seeded.commit()
    assert auth_client.get(f"{API}/hello", headers=H).status_code == 403


def test_upload_token_only_for_servers(auth_client, seeded):
    dev = Client(slug="sw-1", name="SW", kind="network", vendor="huawei", protocol="ftp", mgmt_ip="10.9.9.9")
    seeded.add(dev)
    seeded.commit()
    assert auth_client.post(f"/api/clients/{dev.id}/upload-token").status_code == 404
