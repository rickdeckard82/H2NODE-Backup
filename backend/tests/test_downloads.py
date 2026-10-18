"""Página Downloads: agente Linux montado na hora, envio do instalador, links temporários."""

import gzip
import hashlib
import io
import tarfile
from pathlib import Path

from app.core.config import settings

AGENT_DIR = Path(__file__).resolve().parents[2] / "agent"


def _agent(monkeypatch, tmp_path):
    if AGENT_DIR.is_dir():
        monkeypatch.setattr(settings, "agent_dir", str(AGENT_DIR))
        return
    # imagem de teste sem o repositório: um agente mínimo
    d = tmp_path / "agent"
    d.mkdir()
    (d / "pulse-backup-agent.sh").write_text('#!/bin/bash\nAGENT_VERSION="9.8.7"\n')
    (d / "install.sh").write_text("#!/bin/bash\n")
    (d / "agent.conf.example").write_text("CLIENT_ID=\n")
    monkeypatch.setattr(settings, "agent_dir", str(d))


def test_list_and_download_agent(auth_client, monkeypatch, tmp_path):
    _agent(monkeypatch, tmp_path)
    items = auth_client.get("/api/downloads/list").json()["items"]
    agent = next(i for i in items if i["platform"] == "linux")
    assert agent["name"].startswith("pulse-backup-agent-") and agent["name"].endswith(".tar.gz")
    r = auth_client.get(f"/api/downloads/file/{agent['name']}")
    assert r.status_code == 200
    assert hashlib.sha256(r.content).hexdigest() == agent["sha256"]
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(r.content))) as tf:
        names = {m.name.split("/", 1)[1]: m for m in tf.getmembers()}
    assert set(names) == {"pulse-backup-agent.sh", "install.sh", "agent.conf.example"}
    assert names["install.sh"].mode & 0o111  # executável
    # o mesmo agente gera sempre o mesmo arquivo
    assert auth_client.get(f"/api/downloads/file/{agent['name']}").content == r.content


def test_temporary_link_and_auth(auth_client, client, monkeypatch, tmp_path):
    _agent(monkeypatch, tmp_path)
    name = next(i["name"] for i in auth_client.get("/api/downloads/list").json()["items"] if i["platform"] == "linux")
    link = auth_client.post(f"/api/downloads/{name}/link").json()
    assert "?t=" in link["url"]
    path = link["url"].split(settings.frontend_origin.rstrip("/"), 1)[1]
    client.cookies.clear()  # sem login
    assert client.get(f"/api/downloads/file/{name}").status_code == 401
    assert client.get(path).status_code == 200
    assert client.get(path.replace("?t=", "?t=1")).status_code == 403  # adulterado
    other = path.replace(name, "outro.exe")
    assert client.get(other).status_code == 403  # o link vale só para o próprio arquivo


def test_upload_installer(auth_client, monkeypatch, tmp_path):
    _agent(monkeypatch, tmp_path)
    exe = b"MZ" + b"\x00" * 1000
    assert auth_client.put("/api/downloads/pagina.html", content=b"<script>").status_code == 422
    assert auth_client.put("/api/downloads/pulse-backup-agent-1.0.0.tar.gz", content=b"x").status_code == 422
    r = auth_client.put("/api/downloads/PulseBackup-Setup-0.2.0.exe", content=exe)
    assert r.status_code == 200, r.text
    assert r.json()["platform"] == "windows" and r.json()["version"] == "0.2.0"
    assert r.json()["sha256"] == hashlib.sha256(exe).hexdigest()
    assert auth_client.get("/api/downloads/file/PulseBackup-Setup-0.2.0.exe").content == exe
    assert auth_client.delete("/api/downloads/PulseBackup-Setup-0.2.0.exe").status_code == 204
    assert auth_client.get("/api/downloads/file/PulseBackup-Setup-0.2.0.exe").status_code == 404


def test_built_installer(auth_client, monkeypatch, tmp_path):
    """O instalador do client-builder aparece sozinho, tem prioridade e não pode ser trocado/excluído."""
    _agent(monkeypatch, tmp_path)
    dist = tmp_path / "client-dist"
    dist.mkdir()
    exe = b"MZ" + b"\x01" * 500
    (dist / "PulseBackup-Setup-0.3.0.exe").write_bytes(exe)
    (dist / ".PulseBackup-Setup-0.3.0.exe.tmp").write_bytes(b"MZ")  # cópia pela metade: ignorada
    monkeypatch.setattr(settings, "client_dist_dir", str(dist))
    items = auth_client.get("/api/downloads/list").json()["items"]
    win = [i for i in items if i["platform"] == "windows"]
    assert len(win) == 1 and win[0]["source"] == "build" and win[0]["version"] == "0.3.0"
    assert win[0]["sha256"] == hashlib.sha256(exe).hexdigest()
    assert auth_client.get("/api/downloads/file/PulseBackup-Setup-0.3.0.exe").content == exe
    assert auth_client.put("/api/downloads/PulseBackup-Setup-0.3.0.exe", content=b"MZ").status_code == 409
    assert auth_client.delete("/api/downloads/PulseBackup-Setup-0.3.0.exe").status_code == 404
    assert (dist / "PulseBackup-Setup-0.3.0.exe").read_bytes() == exe


def test_unreadable_file_does_not_hide_the_rest(auth_client, monkeypatch, tmp_path):
    """Arquivo ilegível vira um aviso na página em vez de derrubar a lista inteira."""
    from app.services import downloads

    _agent(monkeypatch, tmp_path)

    def boom():
        raise PermissionError(13, "Permission denied", "/agent/install.sh")

    monkeypatch.setattr(downloads, "agent_bundle", boom)
    r = auth_client.get("/api/downloads")  # endereço antigo continua valendo
    assert r.status_code == 200
    assert not any(i["platform"] == "linux" for i in r.json()["items"])
    [problem] = r.json()["problems"]
    assert problem.startswith("agente Linux (")
    assert problem.endswith("sem permissão de leitura em /agent/install.sh")


def test_only_latest_windows_installer(auth_client, monkeypatch, tmp_path):
    """Instalador antigo enviado à mão some da lista quando há um mais novo."""
    _agent(monkeypatch, tmp_path)
    dist = tmp_path / "client-dist"
    dist.mkdir()
    (dist / "PulseBackup-Setup-0.2.4.exe").write_bytes(b"MZ new")
    monkeypatch.setattr(settings, "client_dist_dir", str(dist))
    assert auth_client.put("/api/downloads/PulseBackup-Setup-0.2.0.exe", content=b"MZ old").status_code == 200
    win = [i for i in auth_client.get("/api/downloads/list").json()["items"] if i["platform"] == "windows"]
    assert [i["name"] for i in win] == ["PulseBackup-Setup-0.2.4.exe"]
    # continua no disco até o administrador excluir
    assert auth_client.delete("/api/downloads/PulseBackup-Setup-0.2.0.exe").status_code == 204
