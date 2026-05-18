"""
GET   /contacts/{email}         — contact profile
PATCH /contacts/{email}/status  — update contact status
Phase 5.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.contact import Contact
from app.models.enums import ContactStatus

router = APIRouter()


class ContactResponse(BaseModel):
    id: int
    email: str
    name: Optional[str]
    company: Optional[str]
    status: str
    account_value: Optional[float]
    churn_risk_score: Optional[float]
    created_at: str
    last_contact_at: Optional[str]


class ContactStatusUpdate(BaseModel):
    status: str
    performed_by: str = "human"


def _to_response(c: Contact) -> ContactResponse:
    return ContactResponse(
        id=c.id,
        email=c.email,
        name=c.name,
        company=c.company,
        status=c.status.value,
        account_value=c.account_value,
        churn_risk_score=c.churn_risk_score,
        created_at=c.created_at.isoformat() if c.created_at else "",
        last_contact_at=c.last_contact_at.isoformat() if c.last_contact_at else None,
    )


@router.get("/{contact_email:path}", response_model=ContactResponse, summary="Get contact profile")
def get_contact(contact_email: str, db: Session = Depends(get_db)) -> ContactResponse:
    c = db.query(Contact).filter(Contact.email == contact_email).first()
    if c is None:
        raise HTTPException(status_code=404, detail=f"Contact {contact_email} not found")
    return _to_response(c)


@router.patch(
    "/{contact_email:path}/status",
    response_model=ContactResponse,
    summary="Update contact status",
)
def update_contact_status(
    contact_email: str,
    payload: ContactStatusUpdate,
    db: Session = Depends(get_db),
) -> ContactResponse:
    c = db.query(Contact).filter(Contact.email == contact_email).first()
    if c is None:
        raise HTTPException(status_code=404, detail=f"Contact {contact_email} not found")

    try:
        new_status = ContactStatus(payload.status)
    except ValueError:
        valid = [s.value for s in ContactStatus]
        raise HTTPException(status_code=422, detail=f"Invalid status. Valid values: {valid}")

    prev = c.status.value
    c.status = new_status
    db.add(AuditLog(
        entity_type="contact",
        entity_id=c.id,
        action="status_change",
        performed_by=payload.performed_by,
        diff={"before": {"status": prev}, "after": {"status": new_status.value}},
    ))
    db.commit()
    db.refresh(c)
    return _to_response(c)
