"""
POST /api/ingest  — Phase 2 full implementation.

Pipeline (in order):
  1. Pydantic validation (FastAPI handles, returns 422 on failure)
  2. Duplicate message_id check → 200 with already_exists=True (idempotent)
  3. Upsert contact row (create on first sight, update last_contact_at on repeat)
  4. Upsert thread row (create with first_seen_at; update last_updated_at on repeat)
  5. Persist email row (body_truncated flag when len > BODY_TRUNCATION_LIMIT)
  6. Run deterministic rule engine
  7. Update email.rule_flags + heuristic_priority_score
  8. If NOT skip_llm_pipeline: fetch thread history → run ClassificationService
  9. Update email with LLM classification results
  10. Update email.status: Processing → Replied | Escalated | Ignored
  11. Return EmailIngestResponse

Safety guarantees:
  - skip_llm_pipeline emails never reach ClassificationService
  - suppress_auto_reply + skip_llm_pipeline together would raise in ClassificationService
    (invariant guard) — but the ingest layer gates on skip_llm_pipeline first
  - All LLM errors produce a safe fallback (requires_human=True) — never raise to caller
  - DB errors surface as 500 via FastAPI's default exception handler
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.action import Action
from app.models.contact import Contact
from app.models.email import Email
from app.models.enums import ContactStatus, EmailStatus
from app.models.thread import Thread
from app.schemas.classification import EmailCategory
from app.schemas.common import ErrorEnvelope
from app.schemas.email import EmailIngestRequest, EmailIngestResponse
from app.api.rag import get_rag_service
from app.services.classification_service import ClassificationService
from app.services.llm_client import get_default_client
from app.services.rule_engine import classify as rule_classify

logger = logging.getLogger(__name__)

router = APIRouter()

# Body longer than this is stored in full but flagged for LLM chunking (Phase 3).
BODY_TRUNCATION_LIMIT = 10_000

# LLM client initialised once at module load; swapped in tests via dependency override.
# Using a module-level singleton avoids re-creating the Gemini model on every request.
_llm_client: ClassificationService | None = None


def _get_classification_service() -> ClassificationService:
    """
    FastAPI dependency that returns the singleton ClassificationService.
    Tests override this with a dependency that injects a FakeLLMClient.
    """
    global _llm_client
    if _llm_client is None:
        try:
            _llm_client = ClassificationService(get_default_client())
        except ValueError as exc:
            # GEMINI_API_KEY not set — return a service that always falls back.
            logger.warning("LLM client unavailable (%s); all emails will require human review", exc)
            _llm_client = ClassificationService(_NoopLLMClient())
    return _llm_client


class _NoopLLMClient:
    """Fallback when no API key is configured (local dev without credentials)."""
    def generate(self, prompt: str) -> str:
        raise RuntimeError("LLM client not configured (GEMINI_API_KEY missing)")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _upsert_contact(db: Session, sender_email: str, timestamp: datetime) -> Contact:
    contact = db.query(Contact).filter(Contact.email == sender_email).first()
    if contact is None:
        contact = Contact(
            email=sender_email,
            status=ContactStatus.ACTIVE,
            last_contact_at=timestamp,
        )
        db.add(contact)
        db.flush()  # get contact.id without committing
    else:
        contact.last_contact_at = timestamp
    return contact


def _upsert_thread(
    db: Session,
    thread_id_str: str,
    sender_email: str,
    subject: str | None,
    contact_id: int,
    timestamp: datetime,
) -> Thread:
    thread = db.query(Thread).filter(Thread.thread_id == thread_id_str).first()
    if thread is None:
        thread = Thread(
            thread_id=thread_id_str,
            subject=subject,
            sender_email=sender_email,
            contact_id=contact_id,
            first_seen_at=timestamp,
            last_updated_at=timestamp,
        )
        db.add(thread)
        db.flush()
    else:
        # Always advance last_updated_at — even out-of-order arrivals update it
        # because we want the thread to reflect "last activity seen", not
        # "latest timestamp received", which could be a delayed replay.
        thread.last_updated_at = datetime.now(tz=timezone.utc)
        if thread.contact_id is None:
            thread.contact_id = contact_id
    return thread


def _fetch_thread_history(db: Session, thread_db_id: int, exclude_message_id: str) -> list[dict]:
    """
    Return all prior emails in this thread, oldest first.
    Excludes the email currently being ingested so the LLM doesn't see the
    current email twice (it already receives it in the prompt's classification section).
    """
    rows = (
        db.query(Email)
        .filter(
            Email.thread_id == thread_db_id,
            Email.message_id != exclude_message_id,
        )
        .order_by(Email.timestamp.asc())
        .all()
    )
    return [
        {
            "message_id": r.message_id,
            "sender":     r.sender,
            "subject":    r.subject,
            "body":       r.body or "",
            "timestamp":  r.timestamp.isoformat() if r.timestamp else "",
        }
        for r in rows
    ]


def _derive_email_status(rule_flags: dict, requires_human: bool) -> EmailStatus:
    if rule_flags.get("skip_llm_pipeline"):
        cat = rule_flags.get("category", "")
        if cat == "Spam":
            return EmailStatus.IGNORED
        # Ransomware / security / legal hard-stops → escalate immediately
        return EmailStatus.ESCALATED
    if requires_human:
        return EmailStatus.ESCALATED
    return EmailStatus.REPLIED


# ─── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/ingest",
    response_model=EmailIngestResponse,
    responses={422: {"model": ErrorEnvelope}},
    summary="Ingest a single customer email",
)
def ingest_email(
    payload: EmailIngestRequest,
    db: Session = Depends(get_db),
    svc: ClassificationService = Depends(_get_classification_service),
) -> EmailIngestResponse:
    """
    Ingest one email, run the rule engine, classify with LLM if eligible,
    and persist results. Idempotent: duplicate message_id returns 200 with
    already_exists=True and the original persisted data.
    """
    # ── 1. Idempotency check ───────────────────────────────────────────────────
    existing = db.query(Email).filter(Email.message_id == payload.message_id).first()
    if existing is not None:
        logger.debug("Duplicate message_id=%s — returning cached result", payload.message_id)
        return EmailIngestResponse(
            message_id=existing.message_id,
            already_exists=True,
            email_id=existing.id,
            thread_id=existing.thread.thread_id,
            priority_score=existing.heuristic_priority_score or 0,
            rule_flags=existing.rule_flags or {},
            status=existing.status.value,
            rag_chunks_used=[],
        )

    # ── 2. Upsert contact ──────────────────────────────────────────────────────
    contact = _upsert_contact(db, payload.sender, payload.timestamp)

    # ── 3. Upsert thread ──────────────────────────────────────────────────────
    thread = _upsert_thread(
        db,
        thread_id_str=payload.thread_id,
        sender_email=payload.sender,
        subject=payload.subject,
        contact_id=contact.id,
        timestamp=payload.timestamp,
    )

    # ── 4. Persist email row ───────────────────────────────────────────────────
    body = payload.body or ""
    email_row = Email(
        thread_id=thread.id,
        message_id=payload.message_id,
        sender=payload.sender,
        subject=payload.subject,
        body=body,
        body_truncated=len(body) > BODY_TRUNCATION_LIMIT,
        timestamp=payload.timestamp,
        status=EmailStatus.PROCESSING,
    )
    db.add(email_row)
    db.flush()  # get email_row.id

    # ── 5. Rule engine ─────────────────────────────────────────────────────────
    email_dict = {
        "message_id": payload.message_id,
        "sender":     payload.sender,
        "subject":    payload.subject or "",
        "body":       body,
        "timestamp":  payload.timestamp.isoformat(),
    }
    rule_result = rule_classify(payload.sender, payload.subject or "", body)
    rule_flags_dict = rule_result.to_dict()

    email_row.heuristic_priority_score = rule_result.priority_score
    email_row.rule_flags = rule_flags_dict

    # ── 6. Classification (LLM layer) ─────────────────────────────────────────
    if not rule_result.skip_llm_pipeline:
        rag_svc = get_rag_service()
        rag_query = f"{payload.subject or ''} {body}".strip()
        rag_results = rag_svc.search(rag_query, top_k=3)
        rag_context = rag_svc.format_for_prompt(rag_results)
        rag_chunks_used = [r.source_doc for r in rag_results]

        thread_history = _fetch_thread_history(db, thread.id, payload.message_id)
        classification = svc.classify(email_dict, thread_history, rule_flags_dict, rag_context=rag_context)

        email_row.sentiment_score = classification.sentiment_score
        email_row.category        = classification.category.value
        email_row.urgency         = classification.urgency.value
        email_row.requires_human  = classification.requires_human
        email_row.confidence      = classification.confidence
        email_row.raw_entities    = classification.detected_entities.model_dump()
        requires_human            = classification.requires_human
    else:
        # skip_llm_pipeline — use rule engine's category for status derivation
        requires_human = True  # hard-stopped emails always need human handling
        rag_chunks_used: list[str] = []

    # ── 7. Final status ────────────────────────────────────────────────────────
    email_row.status = _derive_email_status(rule_flags_dict, requires_human)

    db.commit()
    db.refresh(email_row)

    logger.info(
        "Ingested %s | priority=%d | category=%s | requires_human=%s | status=%s",
        payload.message_id,
        rule_result.priority_score,
        email_row.category or rule_flags_dict.get("category"),
        requires_human,
        email_row.status.value,
    )

    return EmailIngestResponse(
        message_id=email_row.message_id,
        already_exists=False,
        email_id=email_row.id,
        thread_id=thread.thread_id,
        priority_score=rule_result.priority_score,
        rule_flags=rule_flags_dict,
        status=email_row.status.value,
        rag_chunks_used=rag_chunks_used,
    )


# ─── GET /api/emails list ──────────────────────────────────────────────────────

class EmailListItem(BaseModel):
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
    requires_human: Optional[bool]
    thread_id: str


class EmailListResponse(BaseModel):
    total: int
    emails: list[EmailListItem]


@router.get("/emails", response_model=EmailListResponse, summary="List ingested emails")
def list_emails(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> EmailListResponse:
    q = db.query(Email)
    if status:
        try:
            q = q.filter(Email.status == EmailStatus(status))
        except ValueError:
            pass
    total = q.count()
    rows = q.order_by(Email.timestamp.desc()).offset(offset).limit(limit).all()
    return EmailListResponse(
        total=total,
        emails=[
            EmailListItem(
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
                requires_human=r.requires_human,
                thread_id=r.thread.thread_id if r.thread else "",
            )
            for r in rows
        ],
    )


# ─── GET /api/emails/{email_id} detail ────────────────────────────────────────

class ActionSummary(BaseModel):
    id: int
    action_type: str
    proposed_content: Optional[str]
    is_approved: Optional[bool]
    approved_by: Optional[str]
    agent_reasoning_log: Optional[list]
    created_at: str


class EmailDetail(BaseModel):
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
    priority_score: Optional[int]
    requires_human: Optional[bool]
    confidence: Optional[float]
    raw_entities: Optional[dict]
    rule_flags: Optional[dict]
    thread_id: str
    actions: list[ActionSummary]


@router.get("/emails/{email_id}", response_model=EmailDetail, summary="Email detail with actions")
def get_email(email_id: int, db: Session = Depends(get_db)) -> EmailDetail:
    row = db.query(Email).filter(Email.id == email_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Email {email_id} not found")
    actions = db.query(Action).filter(Action.email_id == email_id).order_by(Action.created_at.asc()).all()
    return EmailDetail(
        id=row.id,
        message_id=row.message_id,
        sender=row.sender,
        subject=row.subject,
        body=row.body,
        timestamp=row.timestamp.isoformat() if row.timestamp else "",
        status=row.status.value,
        category=row.category,
        urgency=row.urgency,
        sentiment_score=row.sentiment_score,
        priority_score=row.heuristic_priority_score,
        requires_human=row.requires_human,
        confidence=row.confidence,
        raw_entities=row.raw_entities,
        rule_flags=row.rule_flags,
        thread_id=row.thread.thread_id if row.thread else "",
        actions=[
            ActionSummary(
                id=a.id,
                action_type=a.action_type.value,
                proposed_content=a.proposed_content,
                is_approved=a.is_approved,
                approved_by=a.approved_by,
                agent_reasoning_log=a.agent_reasoning_log,
                created_at=a.created_at.isoformat() if a.created_at else "",
            )
            for a in actions
        ],
    )


# ─── GET /api/status/{job_id} ─────────────────────────────────────────────────

class JobStatusResponse(BaseModel):
    job_id: str
    email_id: Optional[int]
    status: str
    category: Optional[str]
    urgency: Optional[str]
    requires_human: Optional[bool]
    found: bool


@router.get("/status/{job_id}", response_model=JobStatusResponse, summary="Processing status by message_id")
def get_job_status(job_id: str, db: Session = Depends(get_db)) -> JobStatusResponse:
    row = db.query(Email).filter(Email.message_id == job_id).first()
    if row is None:
        return JobStatusResponse(job_id=job_id, email_id=None, status="not_found",
                                  category=None, urgency=None, requires_human=None, found=False)
    return JobStatusResponse(
        job_id=job_id,
        email_id=row.id,
        status=row.status.value,
        category=row.category,
        urgency=row.urgency,
        requires_human=row.requires_human,
        found=True,
    )
