from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean,
    DateTime, Enum, ForeignKey, Index, JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import EmailStatus


class Email(Base):
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("threads.id"), nullable=False)

    # UNIQUE constraint enforces idempotent ingest at the DB level.
    # Application layer also checks before insert to return a clean 200, not a 409.
    message_id = Column(String, nullable=False, unique=True, index=True)

    sender = Column(String, nullable=False)
    subject = Column(String, nullable=True)

    # Body is always stored in full. Truncation for LLM context happens at read-time
    # in the LLM service layer (Phase 2). Truncating on write loses the original
    # and breaks audit trails.
    body = Column(Text, nullable=True)

    # Set to True when the original body exceeded 10,000 characters.
    # The LLM service reads this flag to decide whether chunking is needed.
    body_truncated = Column(Boolean, nullable=False, default=False)

    timestamp = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Rule engine outputs (set synchronously on ingest, never null after ingest) ──

    # 0–100 triage priority assigned by the deterministic rule engine.
    # LLM may surface a refined urgency label in Phase 2, but this score is the
    # baseline used for queue ordering until then.
    heuristic_priority_score = Column(Integer, nullable=True)

    # Full output of RuleEngineResult serialised as a dict.
    # Stores: category, suppress_auto_reply, skip_llm_pipeline, deterministic_route,
    # legal_flag, security_flag, gdpr_flag, matched_rules.
    # Using JSON (not 8 boolean columns) keeps the schema stable as new rules are added.
    rule_flags = Column(JSON, nullable=True)

    # ── LLM outputs (nullable until Phase 2 processing completes) ──────────────
    sentiment_score = Column(Float, nullable=True)  # -1.0 (very negative) to +1.0
    category = Column(String, nullable=True)
    urgency = Column(String, nullable=True)
    requires_human = Column(Boolean, nullable=True)
    confidence = Column(Float, nullable=True)  # 0.0 to 1.0; < 0.70 auto-flags for review

    # Named entity extraction output: {"order_ids": [], "ticket_ids": [],
    # "monetary_amounts": [], "deadlines": [], "products_mentioned": []}
    raw_entities = Column(JSON, nullable=True)

    status = Column(Enum(EmailStatus), nullable=False, default=EmailStatus.RECEIVED)

    thread = relationship("Thread", back_populates="emails")
    actions = relationship("Action", back_populates="email")

    __table_args__ = (
        # Supports sentiment trend queries: WHERE sender = ? AND timestamp > ?
        Index("ix_email_sender_timestamp", "sender", "timestamp"),
    )
