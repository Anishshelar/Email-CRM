"""GET /audit/{entity_type}/{entity_id} — Phase 5."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_log import AuditLog

router = APIRouter()

VALID_ENTITY_TYPES = {"email", "thread", "contact", "action"}


class AuditEntry(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    performed_by: str
    timestamp: str
    diff: Optional[dict]


class AuditLogResponse(BaseModel):
    entity_type: str
    entity_id: int
    entries: list[AuditEntry]


@router.get(
    "/{entity_type}/{entity_id}",
    response_model=AuditLogResponse,
    summary="Audit log for a specific entity",
)
def get_audit_log(
    entity_type: str,
    entity_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> AuditLogResponse:
    rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id,
        )
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return AuditLogResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        entries=[
            AuditEntry(
                id=r.id,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                action=r.action,
                performed_by=r.performed_by,
                timestamp=r.timestamp.isoformat() if r.timestamp else "",
                diff=r.diff,
            )
            for r in rows
        ],
    )
