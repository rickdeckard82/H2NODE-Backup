from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.db import get_db
from app.models import AuditLog
from app.schemas.audit import AuditLogOut
from app.schemas.common import Page

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_admin)])


@router.get("", response_model=Page[AuditLogOut])
def list_audit(
    db: Session = Depends(get_db),
    actor: str | None = None,
    entity_type: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> Page[AuditLogOut]:
    stmt = select(AuditLog)
    if actor:
        stmt = stmt.where(AuditLog.actor_username.ilike(f"%{actor}%"))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if since:
        stmt = stmt.where(AuditLog.created_at >= since)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(page_size).offset((page - 1) * page_size)
    ).scalars()
    return Page(items=[AuditLogOut.model_validate(r) for r in rows],
                total=total, page=page, page_size=page_size)
