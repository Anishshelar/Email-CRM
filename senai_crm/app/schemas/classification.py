"""
Pydantic schema for LLM classification output — Phase 2.

Enforces the exact field names, enum values, and types from spec Component 2 Layer 2.
Business rules are encoded as model validators so they can never be bypassed:
  - Confidence gate: confidence < 0.70 → requires_human=True
  - Critical urgency → requires_human=True
  - suggested_reply is null when requires_human=True (spec rule)
  - escalation_reason is required when requires_human=True
"""

import enum
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator

# Confidence threshold below which automatic human-review escalation is triggered.
# Named constant — not a magic number — so it's auditable and easily changed.
CONFIDENCE_GATE_THRESHOLD = 0.70


class EmailCategory(str, enum.Enum):
    COMPLAINT = "Complaint"
    INQUIRY = "Inquiry"
    BUG_REPORT = "Bug Report"
    FEATURE_REQUEST = "Feature Request"
    COMPLIANCE = "Compliance"
    LEGAL = "Legal"
    BILLING = "Billing"
    SPAM = "Spam"
    INTERNAL = "Internal"
    # "Security" is not in the spec's LLM output schema, but the rule engine uses it
    # for ransomware/login-alert emails that bypass the LLM entirely. It must be a
    # valid EmailCategory so emails.category can be written without a raw string.
    SECURITY = "Security"
    OTHER = "Other"


class Sentiment(str, enum.Enum):
    POSITIVE = "Positive"
    NEUTRAL = "Neutral"
    NEGATIVE = "Negative"
    MIXED = "Mixed"


class Urgency(str, enum.Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class DetectedEntities(BaseModel):
    order_ids: list[str] = []
    ticket_ids: list[str] = []
    monetary_amounts: list[str] = []
    deadlines: list[str] = []
    products_mentioned: list[str] = []


class EmailClassification(BaseModel):
    """
    Structured output from the LLM classification engine.
    Field names and types match the spec exactly.
    """

    category: EmailCategory
    sentiment: Sentiment
    sentiment_score: float        # -1.0 (very negative) … +1.0 (very positive)
    urgency: Urgency
    requires_human: bool
    escalation_reason: Optional[str] = None  # non-null iff requires_human=True
    suggested_reply: Optional[str] = None    # non-null iff requires_human=False
    confidence: float                         # 0.0 … 1.0
    detected_entities: DetectedEntities

    @field_validator("sentiment_score")
    @classmethod
    def clamp_sentiment_score(cls, v: float) -> float:
        # Clamp rather than reject: LLM floating-point may return e.g. 1.0001.
        return round(max(-1.0, min(1.0, v)), 4)

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return round(max(0.0, min(1.0, v)), 4)

    @model_validator(mode="after")
    def apply_business_rules(self) -> "EmailClassification":
        """
        Apply post-validation business rules in priority order.

        Order matters:
          1. Confidence gate — may set requires_human=True first.
          2. Critical urgency — same effect from a different trigger.
          3. Field-consistency enforcement — cleans up conditional fields.
        """
        # ── 1. Confidence gate ────────────────────────────────────────────────
        if self.confidence < CONFIDENCE_GATE_THRESHOLD:
            self.requires_human = True
            if not self.escalation_reason:
                self.escalation_reason = (
                    f"Low-confidence classification "
                    f"({self.confidence:.2f} < {CONFIDENCE_GATE_THRESHOLD} threshold)"
                )

        # ── 2. Critical urgency always requires a human ───────────────────────
        if self.urgency == Urgency.CRITICAL and not self.requires_human:
            self.requires_human = True
            if not self.escalation_reason:
                self.escalation_reason = "Critical urgency — human review required"

        # ── 3. Field-consistency ──────────────────────────────────────────────
        if self.requires_human:
            if not self.escalation_reason:
                self.escalation_reason = "Human review required"
            self.suggested_reply = None   # spec: null when requires_human=True

        return self
