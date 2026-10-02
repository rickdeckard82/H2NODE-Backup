import os

os.environ.setdefault("JWT_SECRET", "test-secret-" + "0" * 32)
os.environ.setdefault("FERNET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("BOOTSTRAP_ADMIN_PASSWORD", "changeme-admin-123")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import get_db  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, SystemRole, SystemUser  # noqa: E402

limiter.enabled = False

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

ADMIN_PW = "changeme-admin-123"


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    """Cada teste com sua própria pasta de backups e volume do sshd."""
    data = tmp_path / "data"
    ssh = tmp_path / "ssh"
    netcfg = tmp_path / "netcfg"
    data.mkdir()
    ssh.mkdir()
    netcfg.mkdir()
    monkeypatch.setattr(settings, "storage_path", str(data))
    monkeypatch.setattr(settings, "ssh_shared_dir", str(ssh))
    monkeypatch.setattr(settings, "receivers_shared_dir", str(netcfg))
    monkeypatch.setattr(settings, "backup_public_key_path", str(tmp_path / "nokey.asc"))
    return tmp_path


@pytest.fixture
def db():
    Base.metadata.create_all(engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def make_user(db, username: str, role: SystemRole, password: str = ADMIN_PW) -> SystemUser:
    u = SystemUser(
        username=username, email=f"{username}@example.com", full_name=username.title(),
        role=role, is_active=True, password_hash=hash_password(password),
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def seeded(db):
    make_user(db, "admin", SystemRole.admin)
    return db


@pytest.fixture
def client(seeded):
    def _override_db():
        yield seeded

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def login(client, username: str = "admin", password: str = ADMIN_PW):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    client.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})
    return client


@pytest.fixture
def auth_client(client):
    return login(client)
