"""
PATCH /drafts/{id}        — edit draft content
POST  /drafts/{id}/approve — approve a draft action
Phase 5.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.action import Action
from app.models.audit_log import AuditLog
from app.models.email import Email
from app.models.enums import ActionType, EmailStatus

router = APIRouter()


class DraftUpdateRequest(BaseModel):
    proposed_content: str


class ApproveRequest(BaseModel):
    approved_by: str = "human"


class DraftResponse(BaseModel):
    id: int
    email_id: int
    action_type: str
    proposed_content: Optional[str]
    is_approved: Optional[bool]
    approved_by: Optional[str]
    executed_at: Optional[str]


def _action_to_response(a: Action) -> DraftResponse:
    return DraftResponse(
        id=a.id,
        email_id=a.email_id,
        action_type=a.action_type.value,
        proposed_content=a.proposed_content,
        is_approved=a.is_approved,
        approved_by=a.approved_by,
        executed_at=a.executed_at.isoformat() if a.executed_at else None,
    )


@router.patch("/{draft_id}", response_model=DraftResponse, summary="Edit a draft's content")
def update_draft(
    draft_id: int,
    payload: DraftUpdateRequest,
    db: Session = Depends(get_db),
) -> DraftResponse:
    action = db.query(Action).filter(Action.id == draft_id).first()
    if action is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    if action.is_approved:
        raise HTTPException(status_code=409, detail="Cannot edit an already-approved draft")

    prev = action.proposed_content
    action.proposed_content = payload.proposed_content
    db.add(AuditLog(
        entity_type="action",
        entity_id=draft_id,
        action="edit_draft",
        performed_by="human",
        diff={"before": {"proposed_content": prev}, "after": {"proposed_content": payload.proposed_content}},
    ))
    db.commit()
    db.refresh(action)
    return _action_to_response(action)


@router.post("/{draft_id}/approve", response_model=DraftResponse, summary="Approve a draft action")
def approve_draft(
    draft_id: int,
    payload: ApproveRequest,
    db: Session = Depends(get_db),
) -> DraftResponse:
    action = db.query(Action).filter(Action.id == draft_id).first()
    if action is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    if action.is_approved:
        raise HTTPException(status_code=409, detail="Draft already approved")

    action.is_approved = True
    action.approved_by = payload.approved_by
    action.executed_at = datetime.now(tz=timezone.utc)

    # Update email status when an auto-reply draft is approved
    if action.action_type == ActionType.AUTO_REPLY:
        email = db.query(Email).filter(Email.id == action.email_id).first()
        if email:
            email.status = EmailStatus.REPLIED

    db.add(AuditLog(
        entity_type="action",
        entity_id=draft_id,
        action="approve_draft",
        performed_by=payload.approved_by,
        diff={"before": {"is_approved": False}, "after": {"is_approved": True, "approved_by": payload.approved_by}},
    ))
    db.commit()
    db.refresh(action)
    return _action_to_response(action)
