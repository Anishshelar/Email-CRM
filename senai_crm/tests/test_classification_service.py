"""
Classification service unit tests — Phase 2.

All tests use a fake in-process LLM client. No network, no API key, no DB.
The fake client satisfies LLMClientProtocol structurally (typing.Protocol),
so no inheritance or patching is needed.

Test coverage:
  1. Happy path — valid JSON classified correctly
  2. Retry path — first response is garbage JSON, second is valid
  3. Fallback path — all MAX_RETRIES+1 attempts fail → safe fallback
  4. Confidence gate — LLM returns confidence=0.5 → requires_human auto-set
  5. Confidence gate — LLM returns confidence=0.9 → requires_human respected
  6. deterministic_route — locked category survives LLM disagreement
  7. skip_llm_pipeline — LLM is never called, safe fallback returned
  8. Critical urgency → requires_human=True always
  9. Missing escalation_reason filled in automatically
 10. suggested_reply nulled when requires_human=True
"""

import json

import pytest

from app.schemas.classification import (
    CONFIDENCE_GATE_THRESHOLD,
    EmailCategory,
    EmailClassification,
    Sentiment,
    Urgency,
)
from app.services.classification_service import (
    MAX_RETRIES,
    ClassificationService,
    _safe_fallback,
    _build_prompt,
)


# ─── Fake LLM client ─────────────────────────────────────────────────────────

class FakeLLMClient:
    """
    Satisfies LLMClientProtocol without any inheritance.
    Pops responses from a queue; raises RuntimeError if exhausted.
    Tracks call count so tests can assert the number of LLM invocations.
    """

    def __init__(self, responses: list[str]) -> None:
        self._queue = list(responses)
        self.call_count = 0

    def generate(self, _prompt: str) -> str:
        self.call_count += 1
        if not self._queue:
            raise RuntimeError("FakeLLMClient: no more responses")
        return self._queue.pop(0)


# ─── Shared fixtures ─────────────────────────────────────────────────────────

# Verbatim from email-data-advanced.json — msg_001 (Alice pricing inquiry)
EMAIL_PRICING = {
    "message_id": "msg_001",
    "sender": "alice.smith@greenlight-npo.org",
    "subject": "Question about pricing",
    "body": (
        "Hi, I was looking at your enterprise plan. Do you offer discounts for "
        "non-profits? We are a registered 501(c)(3) and work with underserved communities."
    ),
    "timestamp": "2023-10-01T09:00:00Z",
}

# Verbatim from email-data-advanced.json — msg_006 (Karen refund complaint)
EMAIL_COMPLAINT = {
    "message_id": "msg_006",
    "sender": "karen.w@retail-co.com",
    "subject": "Refund Request - Order #88271",
    "body": (
        "I am extremely unhappy with the service. The dashboard has been loading slowly "
        "for 3 days and I missed two client deadlines because of it. "
        "I want a full refund for this month immediately."
    ),
    "timestamp": "2023-10-02T11:20:00Z",
}

NO_THREAD: list[dict] = []

NORMAL_RULE_FLAGS = {
    "skip_llm_pipeline": False,
    "deterministic_route": False,
    "suppress_auto_reply": False,
    "category": None,
    "priority_score": 50,
}


def _valid_json(
    category: str = "Inquiry",
    sentiment: str = "Positive",
    sentiment_score: float = 0.6,
    urgency: str = "Low",
    requires_human: bool = False,
    escalation_reason=None,
    suggested_reply: str = "Thank you for reaching out! We offer a 30% non-profit discount.",
    confidence: float = 0.92,
) -> str:
    """Return a minimal valid classification JSON string."""
    return json.dumps({
        "category": category,
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "urgency": urgency,
        "requires_human": requires_human,
        "escalation_reason": escalation_reason,
        "suggested_reply": suggested_reply if not requires_human else None,
        "confidence": confidence,
        "detected_entities": {
            "order_ids": [],
            "ticket_ids": [],
            "monetary_amounts": [],
            "deadlines": [],
            "products_mentioned": ["enterprise plan"],
        },
    })


# ─── 1. Happy path ────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_classification_fields_round_trip(self):
        client = FakeLLMClient([_valid_json()])
        svc = ClassificationService(client)
        result = svc.classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)

        assert isinstance(result, EmailClassification)
        assert result.category == EmailCategory.INQUIRY
        assert result.sentiment == Sentiment.POSITIVE
        assert result.confidence == 0.92
        assert result.requires_human is False
        assert result.suggested_reply is not None

    def test_llm_called_exactly_once_on_success(self):
        client = FakeLLMClient([_valid_json()])
        ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)
        assert client.call_count == 1

    def test_detected_entities_parsed(self):
        payload = _valid_json()
        data = json.loads(payload)
        data["detected_entities"]["monetary_amounts"] = ["$3,240.00"]
        data["detected_entities"]["order_ids"] = ["#88271"]
        client = FakeLLMClient([json.dumps(data)])
        result = ClassificationService(client).classify(EMAIL_COMPLAINT, NO_THREAD, NORMAL_RULE_FLAGS)
        assert "#88271" in result.detected_entities.order_ids
        assert "$3,240.00" in result.detected_entities.monetary_amounts


# ─── 2. Retry path ────────────────────────────────────────────────────────────

class TestRetryPath:
    def test_retries_on_invalid_json(self):
        """First response is garbage; second is valid. Should succeed."""
        client = FakeLLMClient(["not json at all }{", _valid_json()])
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)
        assert result.category == EmailCategory.INQUIRY
        assert client.call_count == 2

    def test_retries_on_empty_response(self):
        """Empty string is invalid; second attempt succeeds."""
        client = FakeLLMClient(["", _valid_json()])
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)
        assert isinstance(result, EmailClassification)
        assert client.call_count == 2

    def test_retries_twice_then_succeeds(self):
        """Two failures then success — uses all retry budget."""
        client = FakeLLMClient(["bad1", "bad2", _valid_json()])
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)
        assert isinstance(result, EmailClassification)
        assert client.call_count == MAX_RETRIES + 1


# ─── 3. Fallback path ─────────────────────────────────────────────────────────

class TestFallbackPath:
    def test_all_retries_exhausted_returns_safe_fallback(self):
        """All MAX_RETRIES+1 attempts fail → safe fallback, never raises."""
        bad_responses = ["bad json"] * (MAX_RETRIES + 1)
        client = FakeLLMClient(bad_responses)
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)

        assert result.requires_human is True
        assert result.confidence == 0.0
        assert result.suggested_reply is None
        assert "failed" in result.escalation_reason.lower()

    def test_fallback_uses_all_retry_budget(self):
        bad_responses = ["bad"] * (MAX_RETRIES + 1)
        client = FakeLLMClient(bad_responses)
        ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)
        assert client.call_count == MAX_RETRIES + 1

    def test_fallback_never_raises(self):
        """The classify() method contract: always returns, never raises."""
        client = FakeLLMClient(["bad"] * (MAX_RETRIES + 1))
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)
        assert isinstance(result, EmailClassification)

    def test_safe_fallback_function_directly(self):
        fb = _safe_fallback("test reason")
        assert fb.requires_human is True
        assert fb.confidence == 0.0
        assert "test reason" in fb.escalation_reason


# ─── 4 & 5. Confidence gate ───────────────────────────────────────────────────

class TestConfidenceGate:
    def test_low_confidence_forces_requires_human(self):
        """LLM returns confidence=0.5 (below 0.70 threshold)."""
        low_conf = _valid_json(confidence=0.5, requires_human=False)
        client = FakeLLMClient([low_conf])
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)

        assert result.requires_human is True, (
            f"confidence=0.5 < {CONFIDENCE_GATE_THRESHOLD} must force requires_human=True"
        )

    def test_low_confidence_adds_escalation_reason(self):
        low_conf = _valid_json(confidence=0.5, requires_human=False)
        client = FakeLLMClient([low_conf])
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)

        assert result.escalation_reason is not None
        assert "0.50" in result.escalation_reason or "confidence" in result.escalation_reason.lower()

    def test_low_confidence_nulls_suggested_reply(self):
        """When confidence gate fires, suggested_reply must be null (spec rule)."""
        low_conf = _valid_json(
            confidence=0.5, requires_human=False,
            suggested_reply="This reply should be suppressed",
        )
        client = FakeLLMClient([low_conf])
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)
        assert result.suggested_reply is None

    def test_high_confidence_preserves_requires_human_false(self):
        """confidence=0.92 (above threshold) — requires_human=False is respected."""
        client = FakeLLMClient([_valid_json(confidence=0.92, requires_human=False)])
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)
        assert result.requires_human is False

    def test_exact_threshold_boundary(self):
        """confidence=0.70 is AT the threshold — should NOT trigger the gate."""
        at_threshold = _valid_json(confidence=0.70, requires_human=False)
        client = FakeLLMClient([at_threshold])
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)
        assert result.requires_human is False

    def test_just_below_threshold_triggers_gate(self):
        """confidence=0.699 — just below threshold — should trigger."""
        just_below = _valid_json(confidence=0.699, requires_human=False)
        client = FakeLLMClient([just_below])
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, NORMAL_RULE_FLAGS)
        assert result.requires_human is True


# ─── 6. deterministic_route ───────────────────────────────────────────────────

class TestDeterministicRoute:
    def test_locked_category_overrides_llm(self):
        """
        Rule engine locked category=Compliance (GDPR).
        LLM returns category=Inquiry.
        After deterministic_route override, result must be Compliance.
        """
        gdpr_rule_flags = {
            "skip_llm_pipeline": False,
            "deterministic_route": True,
            "suppress_auto_reply": True,
            "category": "Compliance",
            "priority_score": 90,
            "gdpr_flag": True,
        }
        # LLM (incorrectly) says Inquiry
        client = FakeLLMClient([_valid_json(category="Inquiry", confidence=0.88)])
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, gdpr_rule_flags)

        assert result.category == EmailCategory.COMPLIANCE, (
            "deterministic_route=True: LLM said Inquiry but rule engine locked Compliance. "
            "This is the GDPR disqualifier scenario."
        )

    def test_locked_legal_category_preserved(self):
        """Cease-and-desist locked as Legal — LLM cannot reclassify."""
        legal_flags = {
            "skip_llm_pipeline": False,
            "deterministic_route": True,
            "category": "Legal",
        }
        client = FakeLLMClient([_valid_json(category="Complaint", confidence=0.85)])
        result = ClassificationService(client).classify(EMAIL_COMPLAINT, NO_THREAD, legal_flags)
        assert result.category == EmailCategory.LEGAL

    def test_llm_enrichment_preserved_under_deterministic_route(self):
        """LLM's sentiment/entities/urgency are kept even when category is overridden."""
        flags = {"skip_llm_pipeline": False, "deterministic_route": True, "category": "Compliance"}
        llm_response = _valid_json(
            category="Inquiry",
            sentiment="Negative",
            sentiment_score=-0.7,
            urgency="High",
            confidence=0.88,
            requires_human=True,
            escalation_reason="Legal obligation",
        )
        client = FakeLLMClient([llm_response])
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, flags)

        # Category locked
        assert result.category == EmailCategory.COMPLIANCE
        # But LLM enrichment is preserved
        assert result.sentiment == Sentiment.NEGATIVE
        assert result.sentiment_score == pytest.approx(-0.7, abs=0.001)
        assert result.urgency == Urgency.HIGH


# ─── 7. skip_llm_pipeline ─────────────────────────────────────────────────────

class TestSkipLLMPipeline:
    def test_skip_pipeline_returns_fallback_without_calling_llm(self):
        """Ransomware / spam: LLM is never called."""
        spam_flags = {
            "skip_llm_pipeline": True,
            "deterministic_route": True,
            "category": "Spam",
            "priority_score": 5,
        }
        client = FakeLLMClient([_valid_json()])  # would fail if called
        result = ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, spam_flags)

        assert client.call_count == 0, "LLM must not be called when skip_llm_pipeline=True"
        assert result.requires_human is True  # safe fallback

    def test_security_threat_not_sent_to_llm(self):
        security_flags = {
            "skip_llm_pipeline": True,
            "deterministic_route": True,
            "category": "Security",
            "priority_score": 100,
        }
        client = FakeLLMClient(["should never be called"])
        ClassificationService(client).classify(EMAIL_PRICING, NO_THREAD, security_flags)
        assert client.call_count == 0


# ─── 8. Critical urgency ──────────────────────────────────────────────────────

class TestCriticalUrgency:
    def test_critical_urgency_forces_requires_human(self):
        """LLM returns urgency=Critical but requires_human=False — must be corrected."""
        critical = _valid_json(urgency="Critical", requires_human=False, confidence=0.88)
        client = FakeLLMClient([critical])
        result = ClassificationService(client).classify(EMAIL_COMPLAINT, NO_THREAD, NORMAL_RULE_FLAGS)
        assert result.requires_human is True

    def test_critical_urgency_nulls_suggested_reply(self):
        critical = _valid_json(
            urgency="Critical", requires_human=False, confidence=0.88,
            suggested_reply="Auto-reply that must be suppressed",
        )
        client = FakeLLMClient([critical])
        result = ClassificationService(client).classify(EMAIL_COMPLAINT, NO_THREAD, NORMAL_RULE_FLAGS)
        assert result.suggested_reply is None


# ─── 9 & 10. Field consistency ───────────────────────────────────────────────

class TestFieldConsistency:
    def test_missing_escalation_reason_filled_in(self):
        """LLM returns requires_human=True but omits escalation_reason."""
        payload = json.loads(_valid_json(requires_human=True, confidence=0.88))
        payload["escalation_reason"] = None
        payload["suggested_reply"] = None
        client = FakeLLMClient([json.dumps(payload)])
        result = ClassificationService(client).classify(EMAIL_COMPLAINT, NO_THREAD, NORMAL_RULE_FLAGS)
        assert result.escalation_reason is not None
        assert len(result.escalation_reason) > 0

    def test_suggested_reply_nulled_when_requires_human(self):
        """LLM returns both requires_human=True AND a suggested_reply — reply must be nulled."""
        payload = json.loads(_valid_json(requires_human=True, confidence=0.88))
        payload["suggested_reply"] = "This reply should be suppressed"
        payload["escalation_reason"] = "Human review needed"
        client = FakeLLMClient([json.dumps(payload)])
        result = ClassificationService(client).classify(EMAIL_COMPLAINT, NO_THREAD, NORMAL_RULE_FLAGS)
        assert result.suggested_reply is None


# ─── Prompt structure ─────────────────────────────────────────────────────────

class TestPromptStructure:
    def test_prompt_contains_rag_placeholder(self):
        """Phase 3 RAG injection point must be present and findable."""
        prompt = _build_prompt(EMAIL_PRICING, NO_THREAD, rag_context=None)
        assert "RAG_INJECTION_POINT" in prompt or "PHASE 3" in prompt

    def test_prompt_includes_thread_history(self):
        """Thread history is included when there are prior messages."""
        thread = [
            {
                "sender": "alice.smith@greenlight-npo.org",
                "subject": "Question about pricing",
                "body": "Hi, I was looking at your enterprise plan.",
                "timestamp": "2023-10-01T09:00:00Z",
            }
        ]
        prompt = _build_prompt(EMAIL_PRICING, thread, rag_context=None)
        assert "alice.smith@greenlight-npo.org" in prompt
        assert "enterprise plan" in prompt

    def test_prompt_includes_email_body(self):
        prompt = _build_prompt(EMAIL_PRICING, NO_THREAD, rag_context=None)
        assert "non-profits" in prompt

    def test_custom_rag_context_replaces_placeholder(self):
        rag = "Retrieved chunk: refund policy states no refunds after 14 days."
        prompt = _build_prompt(EMAIL_PRICING, NO_THREAD, rag_context=rag)
        assert "refund policy" in prompt
        assert "PHASE 3" not in prompt
