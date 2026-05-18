"""GET /threads/{contact_email} — Phase 5."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.email import Email
from app.models.thread import Thread

router = APIRouter()


class EmailInThread(BaseModel):
    id: int
    message_id: str
    sender: str
    subject: Optional[str]
    body: Optional[str]
    timestamp: str
    status: str
    category: Optional[str]
    urgency: Optional[str]
    sentiment_score: Optional[float]
    requires_human: Optional[bool]
    raw_entities: Optional[dict]
    rule_flags: Optional[dict]


class ThreadDetail(BaseModel):
    id: int
    thread_id: str
    subject: Optional[str]
    sender_email: str
    status: str
    first_seen_at: str
    last_updated_at: str
    emails: list[EmailInThread]


class ThreadListResponse(BaseModel):
    contact_email: str
    thread_count: int
    threads: list[ThreadDetail]


@router.get(
    "/{contact_email:path}",
    response_model=ThreadListResponse,
    summary="All threads for a contact email",
)
def get_threads_for_contact(
    contact_email: str,
    db: Session = Depends(get_db),
) -> ThreadListResponse:
    threads = (
        db.query(Thread)
        .filter(Thread.sender_email == contact_email)
        .order_by(Thread.last_updated_at.desc())
        .all()
    )
    if not threads:
        raise HTTPException(status_code=404, detail=f"No threads found for {contact_email}")

    result = []
    for t in threads:
        emails = [
            EmailInThread(
                id=e.id,
                message_id=e.message_id,
                sender=e.sender,
                subject=e.subject,
                body=e.body,
                timestamp=e.timestamp.isoformat() if e.timestamp else "",
                status=e.status.value,
                category=e.category,
                urgency=e.urgency,
                sentiment_score=e.sentiment_score,
                requires_human=e.requires_human,
                raw_entities=e.raw_entities,
                rule_flags=e.rule_flags,
            )
            for e in t.emails
        ]
        result.append(
            ThreadDetail(
                id=t.id,
                thread_id=t.thread_id,
                subject=t.subject,
                sender_email=t.sender_email,
                status=t.status.value,
                first_seen_at=t.first_seen_at.isoformat() if t.first_seen_at else "",
                last_updated_at=t.last_updated_at.isoformat() if t.last_updated_at else "",
                emails=emails,
            )
        )

    return ThreadListResponse(
        contact_email=contact_email,
        thread_count=len(result),
        threads=result,
    )
