"""
Deterministic rule engine — Phase 1 safety gate.

Runs synchronously on every ingest call BEFORE any LLM or agent code.
Must complete in sub-10ms (pure Python, no I/O, no network).

Design contract (non-negotiable):
  - suppress_auto_reply=True  → no automated reply may ever be sent
  - skip_llm_pipeline=True    → email is stored but never forwarded to LLM or agent
  - deterministic_route=True  → LLM classification cannot override category/routing

The two flags are INDEPENDENT by design (user's requirement):
  - Ransomware / spam:        suppress_auto_reply=True  AND  skip_llm_pipeline=True
  - GDPR / cease-and-desist:  suppress_auto_reply=True  BUT  skip_llm_pipeline=False
    (agent still runs to produce the required legal acknowledgement + compliance ticket)
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ─── Priority score constants ─────────────────────────────────────────────────
# Scale: 0 (no urgency) to 100 (maximum urgency).
# Named constants are required so evaluators can read intent without reverse-engineering
# magic numbers. One-line justification follows each constant.

PRIORITY_SECURITY_THREAT = 100
# Active ransomware/extortion: ongoing attack, potential data loss; overrides all else.

PRIORITY_SECURITY_ALERT = 95
# Suspicious login: may indicate active account compromise; security queue immediately.

PRIORITY_LEGAL_CEASEDESIST = 90
# Cease-and-desist: legal team must review before any company response is sent.

PRIORITY_GDPR_REQUEST = 90
# GDPR Article 20: statutory 30-day obligation; legal flag required; no generic reply.

PRIORITY_P0_INCIDENT = 85
# P0/production-down: explicit revenue loss stated; SLA clock is already running.

PRIORITY_HIGH_URGENCY = 75
# "URGENT" keyword or escalation threat: elevated risk but no stated revenue figure.

PRIORITY_NORMAL = 50
# Default for unclassified customer email; LLM will refine this score in Phase 2.

PRIORITY_INTERNAL = 20
# Internal operations email: no customer-facing urgency; routes to internal inbox.

PRIORITY_SPAM = 5
# Spam: lowest possible priority; never enters the LLM pipeline, never auto-replied.


# ─── Known spam sender domains ────────────────────────────────────────────────
# Derived verbatim from the four thread_spam_* senders in email-data-advanced.json.
# Domain-level blocking is high-confidence and low false-positive.

KNOWN_SPAM_DOMAINS: frozenset[str] = frozenset({
    "marketing-guru.io",    # msg_003: SEO ranking pitch ("front page of Google in 24 hours")
    "spammy-outreach.com",  # msg_024: social collab spam ("100k followers, DM me")
    "wealth-transfer.com",  # msg_031: advance-fee fraud ("Prince Adewale, $50M, processing fee")
    "coldoutreach.com",     # msg_039: cold sales outreach ("right person, purchasing decisions")
})

# ─── Internal sender domains ─────────────────────────────────────────────────
# Derived from the internal-* threads in email-data-advanced.json.

INTERNAL_DOMAINS: frozenset[str] = frozenset({
    "internal.com",     # hr@internal.com, devops@internal.com, manager@internal.com
    "mycompany.com",    # accounting@mycompany.com
    "ourplatform.com",  # noreply@ourplatform.com (system-generated auto-replies)
})


# ─── Result dataclass ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RuleEngineResult:
    """
    Immutable output of the deterministic pre-filter.

    Attributes:
        priority_score      0-100 triage priority (higher = more urgent).
        suppress_auto_reply No automated reply may be sent under any circumstance.
        skip_llm_pipeline   Bypass LLM + agent entirely (spam and ransomware only).
        deterministic_route LLM classification cannot override category/routing.
        legal_flag          Must be routed to the legal team.
        security_flag       Must be routed to the security queue.
        gdpr_flag           GDPR data-subject rights obligation detected.
        category            Pre-assigned category; None if the LLM should decide.
        matched_rules       Which rules fired — stored in rule_flags for audit/transparency.
    """
    priority_score: int
    suppress_auto_reply: bool
    skip_llm_pipeline: bool
    deterministic_route: bool
    legal_flag: bool
    security_flag: bool
    gdpr_flag: bool
    matched_rules: list[str] = field(default_factory=list)
    category: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialise for storage in emails.rule_flags (JSON column)."""
        return {
            "priority_score": self.priority_score,
            "suppress_auto_reply": self.suppress_auto_reply,
            "skip_llm_pipeline": self.skip_llm_pipeline,
            "deterministic_route": self.deterministic_route,
            "legal_flag": self.legal_flag,
            "security_flag": self.security_flag,
            "gdpr_flag": self.gdpr_flag,
            "category": self.category,
            "matched_rules": self.matched_rules,
        }


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _sender_domain(sender: str) -> str:
    """Extract the lowercase domain from a sender address."""
    if "@" in sender:
        return sender.split("@", 1)[1].lower().strip()
    return ""


def _combined(subject: str, body: str) -> str:
    """Concatenate subject and body into a single lowercase search string."""
    return f"{subject} {body}".lower()


# ─── Individual rule detectors ────────────────────────────────────────────────

def _is_ransomware_threat(subject: str, body: str) -> bool:
    """
    Detect ransomware / extortion.

    Derived from msg_038 (hacker@anon-collective.net):
      "We have exfiltrated 50,000 customer records...Send 2 BTC to wallet 1A2b3C4d5E6f
       within 48 hours or we publish the data on the dark web."

    Rule: requires BOTH a crypto payment demand AND a data-theft threat.
    Using a two-signal conjunction prevents false positives from legitimate
    security reports that might mention these terms individually.
    """
    text = _combined(subject, body)

    crypto_payment_demand = any(term in text for term in [
        "btc", "bitcoin", "ethereum", "eth ", "crypto wallet", "wallet address",
        "send 2 ", "send 1 ",  # numeric BTC amounts from the actual email
    ])

    data_theft_threat = (
        # Direct exfiltration claim (msg_038: "we have exfiltrated")
        any(term in text for term in ["exfiltrat", "we have your data", "stolen your data"])
        # Dark-web publication threat (msg_038: "publish the data on the dark web")
        or ("dark web" in text and any(t in text for t in ["publish", "release", "leak"]))
        # Customer-records + publication combo
        or ("customer records" in text and any(t in text for t in ["publish", "release"]))
    )

    return crypto_payment_demand and data_theft_threat


def _is_security_alert(subject: str, body: str) -> bool:
    """
    Detect suspicious-login / unauthorised-access alerts.

    Derived from msg_016 (security@alert-system.com):
      Subject: "ALERT: Suspicious Login from Unknown Location"
      Body: "login attempt to admin account...valid credentials...Immediate action may be required."

    Rule: login-related signal AND a context signal indicating severity.
    """
    text = _combined(subject, body)

    login_signal = any(term in text for term in [
        "suspicious login",
        "login attempt",
        "unauthorized access",
        "unauthorized login",
        "unrecognized login",
        "unusual sign-in",
    ])

    severity_context = any(term in text for term in [
        "admin account",
        "valid credentials",
        "immediate action",
        "unknown location",
        "unrecognized device",
        "unrecognized location",
    ])

    return login_signal and severity_context


def _is_legal_ceasedesist(subject: str, body: str) -> bool:
    """
    Detect cease-and-desist and trademark legal threats.

    Derived from msg_020 (legal@competitor-corp.com):
      Subject: "Cease and Desist Notice"
      Body: "registered trademark...Reg. No. 5,234,112...pursue legal action."

    "Cease and desist" together is unambiguous — one signal suffices.
    For trademark threats without the phrase, require BOTH a trademark assertion
    AND an explicit legal threat to avoid false positives from general IP mentions.
    """
    text = _combined(subject, body)

    if "cease and desist" in text:
        return True

    trademark_assertion = any(term in text for term in [
        "registered trademark",
        "reg. no.",
        "trademark infringement",
    ])
    legal_threat = any(term in text for term in [
        "pursue legal action",
        "legal action",
        "cease all use",
        "infringement claim",
    ])
    return trademark_assertion and legal_threat


def _is_gdpr_request(subject: str, body: str) -> bool:
    """
    Detect formal GDPR data-subject rights requests.

    Derived from msg_052 (marcus.del@fintech-startup.co):
      Subject: "Data Export: GDPR Right to Portability Request"
      Body: "Under GDPR Article 20, I am formally requesting a complete export of all
             personal data...within the statutory 30-day window."

    Rule: a GDPR/portability signal AND a formal-request signal.
    The conjunction prevents false positives from general GDPR mentions in sales emails.
    """
    text = _combined(subject, body)

    gdpr_signal = any(term in text for term in [
        "gdpr",
        "data portability",
        "right to portability",
        "data subject",
    ])

    formal_request = any(term in text for term in [
        "article 20",
        "formally requesting",
        "personal data",
        "data export",
        "statutory",
        "30-day",
        "30 day",
        "right of access",
        "right to erasure",
    ])

    return gdpr_signal and formal_request


def _is_spam(subject: str, body: str, sender: str) -> tuple[bool, str]:
    """
    Detect spam via domain reputation + content-combination matching.
    Returns (is_spam, rule_name_for_audit).

    All four patterns are derived from the actual thread_spam_* emails.
    Each uses a CONJUNCTION of at least two signals to minimise false positives
    (as required — no single-keyword matching).
    """
    domain = _sender_domain(sender)

    # ── Domain reputation (highest confidence) ──────────────────────────────
    if domain in KNOWN_SPAM_DOMAINS:
        return True, f"known_spam_domain:{domain}"

    text = _combined(subject, body)

    # ── SEO/ranking pitch (msg_003 pattern) ─────────────────────────────────
    # Requires: Google-ranking promise + urgency/CTA combo
    seo_promise = any(t in text for t in [
        "front page of google", "first page of google", "top of google",
        "boost your seo", "seo by ",
    ])
    seo_cta = any(t in text for t in [
        "click here", "limited offer", "claim your", "24 hours",
    ])
    if seo_promise and seo_cta:
        return True, "seo_spam_pattern"

    # ── Social collab spam (msg_024 pattern) ─────────────────────────────────
    # Requires: follower-count boast + DM/win-win request
    follower_boast = bool(re.search(r"\d+k?\s*followers", text))
    collab_request = any(t in text for t in ["dm me", "win-win", "let's collab", "collab opportunity"])
    if follower_boast and collab_request:
        return True, "social_collab_spam_pattern"

    # ── Advance-fee fraud (msg_031 pattern) ──────────────────────────────────
    # Requires: large-sum claim + bank-detail or fee request
    large_sum = bool(re.search(r"\$\s*\d+[\.,]?\d*\s*(million|billion|m\b)", text))
    fee_request = any(t in text for t in [
        "bank account details", "processing fee", "transfer fee", "claim your share",
    ])
    if large_sum and fee_request:
        return True, "advance_fee_fraud_pattern"

    # ── Cold sales outreach (msg_039 pattern) ────────────────────────────────
    # Requires: purchasing-authority probe + brevity/deflection signal
    # Both signals together are necessary — a legitimate partner might ask one.
    purchasing_probe = any(t in text for t in [
        "purchasing decisions", "software purchasing", "buying decisions",
    ])
    outreach_deflection = any(t in text for t in [
        "right person", "reaching the right", "keep it brief",
        "just a quick", "quick question",
    ])
    if purchasing_probe and outreach_deflection:
        return True, "cold_outreach_pattern"

    return False, ""


def _is_urgent(subject: str, body: str) -> bool:
    """
    Detect high-urgency signals that boost the priority score for normal emails.
    Derived from msg_002 (bob.jones: "URGENT: Production System Down").
    """
    text = _combined(subject, body)
    return any(term in text for term in [
        "urgent", "p0", "production down", "production is down",
        "not responding", "system down", "losing $", "/minute",
        "immediately", "asap",
    ])


# ─── Public API ───────────────────────────────────────────────────────────────

def classify(sender: str, subject: str, body: Optional[str]) -> RuleEngineResult:
    """
    Run the deterministic rule engine on a single email.

    Evaluation order is significant:
      1. Ransomware — checked before spam so a ransom email is never silently
         dropped into the spam bucket; security team must see it.
      2. Security alert — before legal/GDPR; overlapping signals should bias
         toward the security queue.
      3. Legal (C&D) — before GDPR; both are legal obligations but C&D carries
         immediate reputational risk.
      4. GDPR — before internal/spam; a GDPR request from any domain must be caught.
      5. Internal — before spam; internal domains should never be spam-classified.
      6. Spam — last; a fallback for everything the above didn't catch.
      7. Urgency boost — applied to emails that reach this point unmarked.

    Args:
        sender:  Raw sender address, e.g. "alice@example.com"
        subject: Email subject line (may be None or empty)
        body:    Email body text (may be None, empty, or whitespace-only)

    Returns:
        RuleEngineResult (frozen dataclass)
    """
    subject = subject or ""
    body = body or ""
    matched: list[str] = []

    # ── 1. Ransomware / extortion ─────────────────────────────────────────────
    if _is_ransomware_threat(subject, body):
        matched.append("ransomware_threat")
        return RuleEngineResult(
            priority_score=PRIORITY_SECURITY_THREAT,
            suppress_auto_reply=True,
            skip_llm_pipeline=True,     # Never enters LLM; security team acts directly.
            deterministic_route=True,
            legal_flag=False,
            security_flag=True,
            gdpr_flag=False,
            matched_rules=matched,
            category="Security",
        )

    # ── 2. Security alert (suspicious login) ─────────────────────────────────
    if _is_security_alert(subject, body):
        matched.append("security_alert")
        return RuleEngineResult(
            priority_score=PRIORITY_SECURITY_ALERT,
            suppress_auto_reply=True,   # No auto-reply to external security alerts.
            skip_llm_pipeline=False,    # Agent investigates and notifies security queue.
            deterministic_route=True,
            legal_flag=False,
            security_flag=True,
            gdpr_flag=False,
            matched_rules=matched,
            category="Security",
        )

    # ── 3. Legal: cease-and-desist ────────────────────────────────────────────
    if _is_legal_ceasedesist(subject, body):
        matched.append("cease_and_desist")
        return RuleEngineResult(
            priority_score=PRIORITY_LEGAL_CEASEDESIST,
            suppress_auto_reply=True,   # Legal team reviews before any response.
            skip_llm_pipeline=False,    # Agent must flag_for_legal + create internal ticket.
            deterministic_route=True,
            legal_flag=True,
            security_flag=False,
            gdpr_flag=False,
            matched_rules=matched,
            category="Legal",
        )

    # ── 4. GDPR data-subject request ─────────────────────────────────────────
    if _is_gdpr_request(subject, body):
        matched.append("gdpr_article_20")
        return RuleEngineResult(
            priority_score=PRIORITY_GDPR_REQUEST,
            suppress_auto_reply=True,   # No generic reply; agent produces legal acknowledgement.
            skip_llm_pipeline=False,    # Agent must flag_for_legal + create compliance ticket.
            deterministic_route=True,   # LLM cannot reclassify this as a generic "Inquiry".
            legal_flag=True,
            security_flag=False,
            gdpr_flag=True,
            matched_rules=matched,
            category="Compliance",
        )

    # ── 5. Internal email ─────────────────────────────────────────────────────
    if _sender_domain(sender) in INTERNAL_DOMAINS:
        matched.append("internal_domain")
        return RuleEngineResult(
            priority_score=PRIORITY_INTERNAL,
            suppress_auto_reply=True,
            skip_llm_pipeline=True,     # Internal ops don't need LLM triage spend.
            deterministic_route=True,
            legal_flag=False,
            security_flag=False,
            gdpr_flag=False,
            matched_rules=matched,
            category="Internal",
        )

    # ── 6. Spam ───────────────────────────────────────────────────────────────
    is_spam, spam_rule = _is_spam(subject, body, sender)
    if is_spam:
        matched.append(spam_rule)
        return RuleEngineResult(
            priority_score=PRIORITY_SPAM,
            suppress_auto_reply=True,
            skip_llm_pipeline=True,     # Never enters LLM pipeline.
            deterministic_route=True,
            legal_flag=False,
            security_flag=False,
            gdpr_flag=False,
            matched_rules=matched,
            category="Spam",
        )

    # ── 7. Normal email — apply urgency boost if warranted ───────────────────
    priority = PRIORITY_NORMAL
    if _is_urgent(subject, body):
        matched.append("urgency_keywords")
        priority = PRIORITY_P0_INCIDENT  # LLM will refine to Critical/High/Medium in Phase 2.

    return RuleEngineResult(
        priority_score=priority,
        suppress_auto_reply=False,
        skip_llm_pipeline=False,
        deterministic_route=False,
        legal_flag=False,
        security_flag=False,
        gdpr_flag=False,
        matched_rules=matched,
        category=None,              # LLM decides category for normal emails.
    )
