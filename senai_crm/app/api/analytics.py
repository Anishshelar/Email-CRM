"""
GET /analytics/sentiment-trend  — Phase 2 Layer 3.

Returns per-email sentiment scores for a sender over the last N days,
plus a 3-point moving average and an escalation alert when 3+ consecutive
emails have a negative sentiment score (score < 0).

Consecutive-negative detection algorithm:
  Walk the time-sorted scores. Reset a counter to 0 whenever a score >= 0
  is seen. The counter's maximum value is consecutive_negative_count.
  A single pass through the list; O(n).

Design note on sentiment_score vs. category:
  sentiment_score captures emotional tone (-1.0 … +1.0).
  A score < 0 means the customer expressed negative emotion, regardless of
  whether the email was routed to Complaint, Billing, etc.
  This is the right signal to track churn risk — a polite Billing inquiry
  (score ≥ 0) is not the same risk as an angry Complaint (score < 0).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.email import Email

logger = logging.getLogger(__name__)

router = APIRouter()

# Consecutive negative-score emails that trigger the escalation alert.
CONSECUTIVE_NEGATIVE_THRESHOLD = 3

# ─── Response schema ───────────────────────────────────────────────────────────

class SentimentDataPoint(BaseModel):
    message_id: str
    timestamp: str          # ISO-8601
    sentiment_score: float
    category: Optional[str] = None
    urgency: Optional[str] = None


class SentimentTrendResponse(BaseModel):
    sender: str
    days: int
    data_points: list[SentimentDataPoint]
    moving_average: list[float]         # 3-point MA, same length as data_points
    consecutive_negative_count: int     # longest run of score < 0
    escalation_alert: bool              # True if consecutive_negative_count >= threshold
    escalation_threshold: int           # always CONSECUTIVE_NEGATIVE_THRESHOLD


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _moving_average(scores: list[float], window: int = 3) -> list[float]:
    """
    Causal (trailing) moving average: point i averages [max(0,i-window+1)..i].
    Returns a list of the same length — no warm-up gap.
    """
    result = []
    for i, _ in enumerate(scores):
        chunk = scores[max(0, i - window + 1) : i + 1]
        result.append(round(sum(chunk) / len(chunk), 4))
    return result


def _longest_consecutive_negative(scores: list[float]) -> int:
    max_run = 0
    run = 0
    for s in scores:
        if s < 0:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return max_run


# ─── Endpoint ──────────────────────────────────────────────────────────────────

@router.get(
    "/sentiment-trend",
    response_model=SentimentTrendResponse,
    summary="Sentiment trend for a sender over the last N days",
)
def sentiment_trend(
    sender: str = Query(..., description="Sender email address"),
    days: int = Query(30, ge=0, le=3650, description="Look-back window in days; 0 = all time"),
    db: Session = Depends(get_db),
) -> SentimentTrendResponse:
    """
    Return time-series sentiment data for all classified emails from `sender`
    received in the last `days` days. Emails without a sentiment_score (e.g.
    hard-stopped by the rule engine) are excluded from the series but do not
    affect accuracy — they carry no emotional signal.
    """
    q = db.query(Email).filter(
        Email.sender == sender,
        Email.sentiment_score.isnot(None),
    )
    if days > 0:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        q = q.filter(Email.timestamp >= cutoff)
    rows = q.order_by(Email.timestamp.asc()).all()

    data_points = [
        SentimentDataPoint(
            message_id=r.message_id,
            timestamp=r.timestamp.isoformat() if r.timestamp else "",
            sentiment_score=r.sentiment_score,
            category=r.category,
            urgency=r.urgency,
        )
        for r in rows
    ]

    scores = [dp.sentiment_score for dp in data_points]
    moving_avg = _moving_average(scores) if scores else []
    consecutive_neg = _longest_consecutive_negative(scores)

    return SentimentTrendResponse(
        sender=sender,
        days=days,
        data_points=data_points,
        moving_average=moving_avg,
        consecutive_negative_count=consecutive_neg,
        escalation_alert=consecutive_neg >= CONSECUTIVE_NEGATIVE_THRESHOLD,
        escalation_threshold=CONSECUTIVE_NEGATIVE_THRESHOLD,
    )


# ─── Category breakdown ────────────────────────────────────────────────────────

class CategoryBreakdownItem(BaseModel):
    category: str
    count: int


class CategoryBreakdownResponse(BaseModel):
    total: int
    breakdown: list[CategoryBreakdownItem]


@router.get(
    "/category-breakdown",
    response_model=CategoryBreakdownResponse,
    summary="Email count grouped by category",
)
def category_breakdown(db: Session = Depends(get_db)) -> CategoryBreakdownResponse:
    rows = (
        db.query(Email.category, func.count(Email.id))
        .filter(Email.category.isnot(None))
        .group_by(Email.category)
        .order_by(func.count(Email.id).desc())
        .all()
    )
    items = [CategoryBreakdownItem(category=r[0], count=r[1]) for r in rows]
    return CategoryBreakdownResponse(total=sum(i.count for i in items), breakdown=items)
