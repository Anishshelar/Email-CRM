from sqlalchemy import Column, Integer, String, DateTime, JSON, Index
from sqlalchemy.sql import func

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)

    # Polymorphic entity reference — not a DB FK because SQLite doesn't support
    # cross-table polymorphic FKs cleanly and we need to audit multiple entity types.
    # The (entity_type, entity_id) pair is indexed together for the
    # GET /audit/{entity_type}/{entity_id} endpoint.
    entity_type = Column(String, nullable=False)  # "email" | "thread" | "contact" | "action"
    entity_id = Column(Integer, nullable=False)

    action = Column(String, nullable=False)  # e.g. "ingest", "status_change", "approve_draft"

    # "agent" for automated actions; user email/ID for human actions.
    performed_by = Column(String, nullable=False)

    timestamp = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Before/after state for human-in-the-loop fine-tuning and change tracking.
    # Schema: {"before": {...}, "after": {...}}
    diff = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_timestamp", "timestamp"),
    )
