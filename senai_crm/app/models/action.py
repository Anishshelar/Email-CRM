from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Enum, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import ActionType


class Action(Base):
    __tablename__ = "actions"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("emails.id"), nullable=False)

    # Structured ReAct trace: list of {"thought": "...", "action": "...",
    # "observation": "..."} dicts produced by the autonomous agent (Phase 3).
    # Stored as JSON (not TEXT) so individual steps are queryable without parsing.
    agent_reasoning_log = Column(JSON, nullable=True)

    action_type = Column(Enum(ActionType), nullable=False)

    # Draft reply text or escalation brief — editable by a human before approval.
    proposed_content = Column(Text, nullable=True)

    # None = pending review; True = approved; False = rejected
    is_approved = Column(Boolean, nullable=True)

    # "agent" when auto-executed; user email/ID when a human approved.
    # Supports both automated and human-in-the-loop flows.
    approved_by = Column(String, nullable=True)

    executed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    email = relationship("Email", back_populates="actions")
