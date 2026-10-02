import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    actor_id: int | None = None,
    actor_username: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    before: Any = None,
    after: Any = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            actor_system_user_id=actor_id,
            actor_username=actor_username,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:255] or None,
            before_json=_dump(before),
            after_json=_dump(after),
        )
    )
