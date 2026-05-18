from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import ThreadStatus


class Thread(Base):
    __tablename__ = "threads"

    # Surrogate PK — used for all FK joins (fast integer comparisons).
    id = Column(Integer, primary_key=True, index=True)

    # Natural key from the JSON dataset. Unique and indexed for external lookups
    # (e.g. GET /threads/{thread_id}). Survives DB migration without breaking
    # external references because it never changes.
    thread_id = Column(String, nullable=False, unique=True, index=True)

    subject = Column(String, nullable=True)

    # Denormalised from contacts for fast thread-by-sender queries
    # (spec requires GET /threads/{contact_email}). Avoids a join through emails.
    sender_email = Column(String, nullable=False, index=True)

    # FK to contacts.id — nullable because the contact row is created on first
    # email ingest; if contact creation races the thread creation, it is set later.
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)

    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_updated_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(ThreadStatus), nullable=False, default=ThreadStatus.OPEN)
    assigned_to = Column(String, nullable=True)

    contact = relationship("Contact", back_populates="threads")
    emails = relationship(
        "Email",
        back_populates="thread",
        order_by="Email.timestamp",  # always chronological
    )

    __table_args__ = (
        Index("ix_thread_sender_updated", "sender_email", "last_updated_at"),
    )
