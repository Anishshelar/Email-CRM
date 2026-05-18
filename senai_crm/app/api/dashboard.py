"""GET /dashboard/stats — Phase 5."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.contact import Contact
from app.models.email import Email
from app.models.enums import EmailStatus
from app.models.thread import Thread

router = APIRouter()


class EmailSummary(BaseModel):
    id: int
    message_id: str
    sender: str
    subject: Optional[str]
    timestamp: str
    status: str
    category: Optional[str]
    urgency: Optional[str]
    sentiment_score: Optional[float]
    priority_score: Optional[int]


class AtRiskContact(BaseModel):
    email: str
    name: Optional[str]
    company: Optional[str]
    account_value: Optional[float]
    churn_risk_score: Optional[float]


class DashboardStats(BaseModel):
    total_emails: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_urgency: dict[str, int]
    escalation_alert_count: int
    recent_emails: list[EmailSummary]
    at_risk_contacts: list[AtRiskContact]


@router.get("/stats", response_model=DashboardStats, summary="Dashboard aggregate statistics")
def dashboard_stats(db: Session = Depends(get_db)) -> DashboardStats:
    total = db.query(func.count(Email.id)).scalar() or 0

    status_rows = (
        db.query(Email.status, func.count(Email.id))
        .group_by(Email.status)
        .all()
    )
    by_status = {row[0].value: row[1] for row in status_rows}

    category_rows = (
        db.query(Email.category, func.count(Email.id))
        .filter(Email.category.isnot(None))
        .group_by(Email.category)
        .all()
    )
    by_category = {row[0]: row[1] for row in category_rows}

    urgency_rows = (
        db.query(Email.urgency, func.count(Email.id))
        .filter(Email.urgency.isnot(None))
        .group_by(Email.urgency)
        .all()
    )
    by_urgency = {row[0]: row[1] for row in urgency_rows}

    escalation_count = (
        db.query(func.count(Email.id))
        .filter(Email.status == EmailStatus.ESCALATED)
        .scalar()
        or 0
    )

    recent_rows = (
        db.query(Email)
        .order_by(Email.timestamp.desc())
        .limit(50)
        .all()
    )
    recent_emails = [
        EmailSummary(
            id=r.id,
            message_id=r.message_id,
            sender=r.sender,
            subject=r.subject,
            timestamp=r.timestamp.isoformat() if r.timestamp else "",
            status=r.status.value,
            category=r.category,
            urgency=r.urgency,
            sentiment_score=r.sentiment_score,
            priority_score=r.heuristic_priority_score,
        )
        for r in recent_rows
    ]

    at_risk = (
        db.query(Contact)
        .filter(Contact.churn_risk_score >= 0.7)
        .order_by(Contact.churn_risk_score.desc())
        .limit(20)
        .all()
    )
    at_risk_contacts = [
        AtRiskContact(
            email=c.email,
            name=c.name,
            company=c.company,
            account_value=c.account_value,
            churn_risk_score=c.churn_risk_score,
        )
        for c in at_risk
    ]

    return DashboardStats(
        total_emails=total,
        by_status=by_status,
        by_category=by_category,
        by_urgency=by_urgency,
        escalation_alert_count=escalation_count,
        recent_emails=recent_emails,
        at_risk_contacts=at_risk_contacts,
    )
