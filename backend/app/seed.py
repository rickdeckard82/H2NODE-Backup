"""Seed idempotente: primeiro admin do painel.

Executado no start do container (ver Dockerfile) e via `make seed`.
"""

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging, logger
from app.core.security import hash_password
from app.models import SystemRole, SystemUser


def seed_admin(db) -> None:
    if db.execute(select(SystemUser).limit(1)).first():
        return
    if not settings.bootstrap_admin_password:
        logger.warning("seed_admin_skipped", reason="BOOTSTRAP_ADMIN_PASSWORD vazio")
        return
    db.add(
        SystemUser(
            username=settings.bootstrap_admin_username,
            email=settings.bootstrap_admin_email,
            full_name="Administrador",
            role=SystemRole.admin,
            is_active=True,
            password_hash=hash_password(settings.bootstrap_admin_password),
        )
    )
    logger.info("seed_admin_created", username=settings.bootstrap_admin_username)


def main() -> None:
    configure_logging()
    db = SessionLocal()
    try:
        seed_admin(db)
        db.commit()
        logger.info("seed_done")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
