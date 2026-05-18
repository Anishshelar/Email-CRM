"""
LLM Classification Service — Phase 2.

Pipeline position:
  POST /api/ingest
    → Pydantic validation
    → Rule engine  (deterministic, sub-10ms)
    → THIS SERVICE  (LLM, ~500ms-2s, only for eligible emails)
    → Persist results to emails table

Responsibilities:
  1. Build a structured prompt (thread history + RAG placeholder + instructions)
  2. Call Gemini with retry / fallback on bad output
  3. Apply the confidence gate (< 0.70 → requires_human=True)
  4. Honour deterministic_route: LLM cannot override the rule engine's locked category
  5. Return a valid EmailClassification — NEVER raise to the caller

Conflicting-signal resolution strategy (documented here for README walkthrough):
  When an email contains mixed signals (e.g. "I love the product but I want a
  refund and will post a public review"), routing fields (category, urgency,
  requires_human) are determined by the MOST SEVERE signal present.
  Severity ladder: Legal ≥ Security ≥ Billing dispute ≥ Complaint ≥ Feature Request ≥ Inquiry
  The sentiment/sentiment_score fields reflect the overall emotional tone, not
  the routing severity. This separation lets the agent express empathy in a reply
  while escalating to the correct queue.
  Triggers that force requires_human=True regardless of positive sentiment:
    public review threat, legal action mention, billing dispute, GDPR reference,
    any Critical urgency signal.
"""

import json
import logging
from typing import Optional

from pydantic import ValidationError

from app.schemas.classification import (
    CONFIDENCE_GATE_THRESHOLD,
    DetectedEntities,
    EmailCategory,
    EmailClassification,
    Sentiment,
    Urgency,
)
from app.services.llm_client import LLMClientProtocol

logger = logging.getLogger(__name__)

# ─── Retry configuration ──────────────────────────────────────────────────────

# 1 initial attempt + MAX_RETRIES retries = MAX_RETRIES+1 total LLM calls.
# Kept deliberately small: each failure adds ~500ms latency to ingest.
# The safe fallback (requires_human=True) is an acceptable outcome after 3 tries.
MAX_RETRIES = 2


# ─── Prompt components ────────────────────────────────────────────────────────

# System prompt is sent once per classification. It defines the assistant's role,
# the conflict-resolution strategy, and the output contract.
_SYSTEM_PROMPT = """\
You are an expert CRM triage specialist for a B2B SaaS company.
Your sole task is to analyse a customer email (with its full thread history) and \
return a single JSON classification object. No other text, no markdown fences.

CONFLICT RESOLUTION — apply when an email contains mixed signals:
  Severity ladder for routing (highest wins): Legal ≥ Security ≥ Billing dispute \
≥ Complaint ≥ Feature Request ≥ Inquiry ≥ Other
  - "I love the product but want a refund and may post a public review" →
      category=Complaint, urgency=High, requires_human=true
  - Any mention of legal action, trademarks, lawsuits, or cease-and-desist →
      category=Legal regardless of positive tone
  - Public review threats (G2, Trustpilot, Twitter) → requires_human=true
  - The `sentiment` and `sentiment_score` fields capture emotional tone only.
  - `category`, `urgency`, and `requires_human` always reflect the worst-case signal.
  - If confidence in your classification is below 0.70, set requires_human=true.
"""

# Injected when no RAG context is available (Phase 1 and 2).
# Phase 3 replaces this constant with retrieved KB chunks.
# SEARCH TAG: RAG_INJECTION_POINT — find this string to wire up Phase 3 RAG.
_RAG_PLACEHOLDER = """\
[PHASE 3 — RAG CONTEXT NOT YET AVAILABLE]
In Phase 3, this section will contain the top-3 most relevant chunks retrieved
from the internal knowledge base, including:
  • pricing_policy.md  (pricing tiers, non-profit discounts, pro-rata billing)
  • sla_policy.md      (uptime SLA, incident response times, credit formula)
  • refund_policy.md   (14-day refund window, retention playbook)
  • api_docs.md        (rate limits, v1 deprecation, v2 breaking changes)
  • compliance_faq.md  (HIPAA BAA, GDPR DPA, SOC 2 Type II)
  • escalation_matrix.md (who handles legal threats, security, PR crises, VIP churn)
Each chunk will include: source document name, chunk text, and similarity score.
Classify using email content and thread history only for now.\
"""

# Schema shown to the LLM in the user message. Using a concrete example (not just
# a TypeScript-style type) helps models produce the exact shape we expect.
_SCHEMA_EXAMPLE = json.dumps(
    {
        "category": "Complaint|Inquiry|Bug Report|Feature Request|Compliance|Legal|Billing|Spam|Internal|Other",
        "sentiment": "Positive|Neutral|Negative|Mixed",
        "sentiment_score": 0.0,
        "urgency": "Critical|High|Medium|Low",
        "requires_human": True,
        "escalation_reason": "string — required when requires_human=true, null otherwise",
        "suggested_reply": "string — required when requires_human=false, null otherwise",
        "confidence": 0.91,
        "detected_entities": {
            "order_ids": ["#88271"],
            "ticket_ids": ["#11042"],
            "monetary_amounts": ["$1,240.00"],
            "deadlines": ["October 30th"],
            "products_mentioned": ["Enterprise plan"],
        },
    },
    indent=2,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _format_thread_history(thread_history: list[dict]) -> str:
    """
    Render prior thread emails as a numbered, human-readable block.
    Oldest first so the LLM reads the conversation in natural order.

    Each entry includes sender, timestamp, subject, and body so the LLM has
    full context without any fields being silently dropped.
    """
    if not thread_history:
        return "(No prior emails in this thread — this is the first message.)"

    lines: list[str] = []
    for i, msg in enumerate(thread_history, start=1):
        lines.append(
            f"[{i}/{len(thread_history)}] "
            f"From: {msg.get('sender', '?')}  |  "
            f"Sent: {msg.get('timestamp', '?')}"
        )
        lines.append(f"Subject: {msg.get('subject', '(no subject)')}")
        body = (msg.get("body") or "").strip()
        lines.append(body if body else "(empty body)")
        if i < len(thread_history):
            lines.append("─" * 60)

    return "\n".join(lines)


def _build_prompt(
    email: dict,
    thread_history: list[dict],
    rag_context: str | None,
) -> str:
    """
    Assemble the full prompt string sent to Gemini.

    Structure:
      SYSTEM PROMPT
      ── THREAD HISTORY ──
      ── EMAIL TO CLASSIFY ──
      ── KNOWLEDGE BASE CONTEXT ──   ← RAG injection point for Phase 3
      ── CLASSIFICATION INSTRUCTIONS ──

    The system prompt is prepended inline (not via a separate system role) because
    google-generativeai's generate_content treats all input as a single user turn
    when called with a plain string. The structure is still clear to the model.
    """
    rag_section = rag_context if rag_context is not None else _RAG_PLACEHOLDER

    body_text = (email.get("body") or "").strip() or "(empty body)"

    return f"""\
{_SYSTEM_PROMPT}

=== THREAD HISTORY ({len(thread_history)} prior email(s)) ===
{_format_thread_history(thread_history)}

=== EMAIL TO CLASSIFY ===
From:      {email.get('sender', '?')}
Subject:   {email.get('subject') or '(no subject)'}
Sent:      {email.get('timestamp', '?')}

{body_text}

=== KNOWLEDGE BASE CONTEXT ===
{rag_section}

=== CLASSIFICATION INSTRUCTIONS ===
Classify the email above. Respond with EXACTLY this JSON structure — no extra keys,
no markdown fences, no explanatory text before or after the JSON:

{_SCHEMA_EXAMPLE}

Rules:
1.  category       — one of: Complaint, Inquiry, Bug Report, Feature Request,
                     Compliance, Legal, Billing, Spam, Internal, Other
2.  sentiment      — one of: Positive, Neutral, Negative, Mixed
3.  sentiment_score — float in [-1.0, +1.0]  (-1.0 = maximally negative)
4.  urgency        — one of: Critical, High, Medium, Low
5.  requires_human — true if urgency=Critical, OR if the email involves legal /
                     security / billing / churn / complaint concerns, OR if your
                     confidence is below {CONFIDENCE_GATE_THRESHOLD}
6.  escalation_reason — concise string if requires_human=true; null otherwise
7.  suggested_reply   — professional, empathetic draft reply if requires_human=false;
                        null if requires_human=true
8.  confidence     — 0.0–1.0; your certainty in this classification
9.  detected_entities — extract ALL order IDs, ticket IDs, monetary amounts,
                        deadlines, and product names visible in the email body
"""


def _safe_fallback(reason: str) -> EmailClassification:
    """
    Safe default when all LLM attempts fail.

    requires_human=True + confidence=0.0 ensures:
      - No automated action is ever taken on an unclassified email.
      - The confidence gate in EmailClassification will also fire (belt + braces).
    urgency=HIGH (not Critical) avoids flooding the critical queue with noise,
    while still surfacing the email for human attention promptly.
    """
    return EmailClassification(
        category=EmailCategory.OTHER,
        sentiment=Sentiment.NEUTRAL,
        sentiment_score=0.0,
        urgency=Urgency.HIGH,
        requires_human=True,
        escalation_reason=f"LLM classification failed — {reason}",
        suggested_reply=None,
        confidence=0.0,
        detected_entities=DetectedEntities(),
    )


# ─── Service class ────────────────────────────────────────────────────────────

class ClassificationService:
    """
    Classifies a single email using Gemini with retry and deterministic override.

    Usage:
        client = GeminiClient()          # once at startup
        svc    = ClassificationService(client)
        result = svc.classify(email_dict, thread_history, rule_flags)
    """

    def __init__(self, client: LLMClientProtocol) -> None:
        self._client = client

    # ── Public API ────────────────────────────────────────────────────────────

    def classify(
        self,
        email: dict,
        thread_history: list[dict],
        rule_flags: dict,
        rag_context: str | None = None,
    ) -> EmailClassification:
        """
        Classify one email and return an EmailClassification.

        Args:
            email:          Dict with keys: message_id, sender, subject, body, timestamp
            thread_history: List of prior emails in the same thread (oldest first)
            rule_flags:     Output of rule_engine.classify().to_dict()
            rag_context:    Retrieved KB chunks (Phase 3); pass None in Phase 2

        Returns:
            EmailClassification — always; never raises.

        Safety guarantees:
            • skip_llm_pipeline=True  → returns safe fallback immediately (never calls LLM)
            • deterministic_route=True → LLM result category is overridden with the
              locked category from rule_flags
            • All LLM failures → safe fallback with requires_human=True
        """
        # Invariant: if both flags are set, the ingest pipeline made an error.
        # suppress_auto_reply emails that skip the LLM (ransomware, spam) must
        # never reach this service — the rule engine should have stopped them.
        # GDPR/C&D emails have suppress_auto_reply=True but skip_llm_pipeline=False,
        # so they correctly continue through to classification.
        if rule_flags.get("skip_llm_pipeline") and rule_flags.get("suppress_auto_reply"):
            raise ValueError(
                f"Invariant violation: email {email.get('message_id')!r} has "
                "suppress_auto_reply=True and skip_llm_pipeline=True — it must "
                "never reach ClassificationService. Rule engine category: "
                f"{rule_flags.get('category')!r}. Check the ingest pipeline."
            )

        # Guard: this email was hard-stopped by the rule engine (LLM not needed).
        if rule_flags.get("skip_llm_pipeline"):
            locked_cat = rule_flags.get("category", "Other")
            logger.debug(
                "Skipping LLM for %s — skip_llm_pipeline=True (category=%s)",
                email.get("message_id"),
                locked_cat,
            )
            return _safe_fallback(f"skip_llm_pipeline=True (rule engine category: {locked_cat})")

        prompt = _build_prompt(email, thread_history, rag_context)

        try:
            raw_json = self._call_with_retry(prompt)
            classification = self._parse_and_validate(raw_json)
        except Exception as exc:
            logger.error(
                "Classification failed for %s after all retries: %s",
                email.get("message_id"),
                exc,
            )
            return _safe_fallback(str(exc))

        # Apply deterministic_route override AFTER LLM classification.
        # The LLM enriches sentiment/entities/reply; the locked category is preserved.
        if rule_flags.get("deterministic_route") and rule_flags.get("category"):
            try:
                locked = EmailCategory(rule_flags["category"])
            except ValueError:
                locked = EmailCategory.OTHER
            if classification.category != locked:
                logger.info(
                    "deterministic_route override: LLM said %r → locked to %r",
                    classification.category.value,
                    locked.value,
                )
                classification = classification.model_copy(update={"category": locked})

        return classification

    # ── Private helpers ───────────────────────────────────────────────────────

    def _call_with_retry(self, prompt: str) -> str:
        """
        Call the LLM up to MAX_RETRIES+1 times.

        On the first failure (JSON parse error or empty response), appends the
        error to the prompt and retries. The error message gives the LLM exactly
        what went wrong so it can self-correct rather than repeating the mistake.

        Raises RuntimeError if all attempts fail (caller catches and uses fallback).
        """
        current_prompt = prompt
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                raw = self._client.generate(current_prompt)
                if not raw or not raw.strip():
                    raise ValueError("LLM returned an empty response")
                # Verify it parses as JSON before returning — catches fences/preamble
                # that slipped past JSON mode (rare but observed with some model versions).
                json.loads(raw)
                return raw
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LLM attempt %d/%d failed for prompt hash %s: %s",
                    attempt + 1,
                    MAX_RETRIES + 1,
                    hash(prompt) % 100_000,  # stable short identifier for log correlation
                    exc,
                )
                if attempt < MAX_RETRIES:
                    current_prompt = (
                        prompt
                        + f"\n\n[RETRY INSTRUCTION — attempt {attempt + 2}]\n"
                        + f"Your previous response was invalid: {exc}\n"
                        + "Please respond again with ONLY a valid JSON object matching "
                        + "the schema above. No markdown, no explanation."
                    )

        raise RuntimeError(
            f"All {MAX_RETRIES + 1} LLM attempts failed. Last error: {last_exc}"
        )

    def _parse_and_validate(self, raw_json: str) -> EmailClassification:
        """
        Parse raw LLM output and validate it against EmailClassification.

        Pydantic validators in EmailClassification handle:
          - Clamping out-of-range floats
          - Confidence gate (< 0.70 → requires_human)
          - Critical urgency → requires_human
          - Field consistency (escalation_reason / suggested_reply nullability)

        Raises ValidationError if the structure is irrecoverably wrong
        (e.g. missing required fields). Caller retries or falls back.
        """
        data = json.loads(raw_json)
        return EmailClassification.model_validate(data)
