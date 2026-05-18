"""POST /respond/{email_id} — Phase 5. Manual human response."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.action import Action
from app.models.audit_log import AuditLog
from app.models.email import Email
from app.models.enums import ActionType, EmailStatus

router = APIRouter()


class RespondRequest(BaseModel):
    content: str
    performed_by: str = "human"


class RespondResponse(BaseModel):
    email_id: int
    action_id: int
    status: str


@router.post(
    "/{email_id}",
    response_model=RespondResponse,
    summary="Manually respond to an email",
)
def respond_to_email(
    email_id: int,
    payload: RespondRequest,
    db: Session = Depends(get_db),
) -> RespondResponse:
    email_row = db.query(Email).filter(Email.id == email_id).first()
    if email_row is None:
        raise HTTPException(status_code=404, detail=f"Email {email_id} not found")

    action = Action(
        email_id=email_id,
        action_type=ActionType.AUTO_REPLY,
        proposed_content=payload.content,
        is_approved=True,
        approved_by=payload.performed_by,
        executed_at=datetime.now(tz=timezone.utc),
    )
    db.add(action)

    prev_status = email_row.status
    email_row.status = EmailStatus.REPLIED
    db.flush()

    db.add(AuditLog(
        entity_type="email",
        entity_id=email_id,
        action="manual_reply",
        performed_by=payload.performed_by,
        diff={"before": {"status": prev_status.value}, "after": {"status": EmailStatus.REPLIED.value}},
    ))
    db.commit()

    return RespondResponse(
        email_id=email_id,
        action_id=action.id,
        status=email_row.status.value,
    )
