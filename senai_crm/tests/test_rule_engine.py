"""
Rule engine unit tests — Phase 1.

These tests are pure functions: no DB, no network, no FastAPI.
They cover every automatic disqualifier from the spec's evaluation criteria.

Test data is copied verbatim from email-data-advanced.json so the assertions
are grounded in the actual dataset, not synthetic approximations.
"""
import pytest
from app.services.rule_engine import (
    classify,
    RuleEngineResult,
    PRIORITY_SECURITY_THREAT,
    PRIORITY_SECURITY_ALERT,
    PRIORITY_LEGAL_CEASEDESIST,
    PRIORITY_GDPR_REQUEST,
    PRIORITY_SPAM,
    PRIORITY_NORMAL,
    PRIORITY_P0_INCIDENT,
)


# ─── Verbatim email fixtures from email-data-advanced.json ───────────────────

MSG_038 = dict(
    sender="hacker@anon-collective.net",
    subject="We have your data - Pay Now",
    body=(
        "We have exfiltrated 50,000 customer records from your database. "
        "Send 2 BTC to wallet 1A2b3C4d5E6f within 48 hours or we publish "
        "the data on the dark web."
    ),
)

MSG_052 = dict(
    sender="marcus.del@fintech-startup.co",
    subject="Data Export: GDPR Right to Portability Request",
    body=(
        "Under GDPR Article 20, I am formally requesting a complete export of all "
        "personal data your platform holds about me "
        "(account: marcus.del@fintech-startup.co). "
        "Please provide this within the statutory 30-day window."
    ),
)

MSG_003 = dict(
    sender="spam.bot@marketing-guru.io",
    subject="Boost your SEO by 300%",
    body=(
        "Dear Sir/Madam, we can get you on the front page of Google in 24 hours "
        "for just $99. Limited offer! Click here to claim."
    ),
)

MSG_024 = dict(
    sender="marketing@spammy-outreach.com",
    subject="Collab opportunity??",
    body=(
        "Hey! Let's collab. You post about us on LinkedIn (100k followers!), "
        "we post about you. Pure win-win. DM me."
    ),
)

MSG_031 = dict(
    sender="prince.nigeria@wealth-transfer.com",
    subject="CONFIDENTIAL: Inheritance of $50,000,000 USD",
    body=(
        "I am Prince Adewale. I have $50 million USD for you. "
        "Please send your bank account details and a processing fee of $500 "
        "to claim your share."
    ),
)

MSG_039 = dict(
    sender="sales@coldoutreach.com",
    subject="Quick question for the right person",
    body=(
        "Hi there - just want to make sure I'm reaching the right person. "
        "Are you responsible for software purchasing decisions at your company? "
        "Happy to keep it brief."
    ),
)

MSG_016 = dict(
    sender="security@alert-system.com",
    subject="ALERT: Suspicious Login from Unknown Location",
    body=(
        "We detected a login attempt to admin account from IP 175.45.176.3 "
        "(Pyongyang, North Korea) at 11:42 UTC. The attempt used valid credentials. "
        "Immediate action may be required."
    ),
)

MSG_020 = dict(
    sender="legal@competitor-corp.com",
    subject="Cease and Desist Notice",
    body=(
        "Your latest ad campaign uses the phrase 'Workflow Unleashed' which is a "
        "registered trademark of Competitor Corp (Reg. No. 5,234,112). "
        "Cease all use immediately or we will pursue legal action."
    ),
)

MSG_002 = dict(
    sender="bob.jones@enterprise.net",
    subject="URGENT: Production System Down",
    body=(
        "Our production server is not responding since 08:50 UTC. "
        "We are losing approximately $10,000/minute. "
        "We need support immediately. This is a P0 incident."
    ),
)

MSG_001 = dict(
    sender="alice.smith@greenlight-npo.org",
    subject="Question about pricing",
    body=(
        "Hi, I was looking at your enterprise plan. "
        "Do you offer discounts for non-profits? "
        "We are a registered 501(c)(3) and work with underserved communities."
    ),
)


# ─── DISQUALIFIER: Ransomware threat ─────────────────────────────────────────

class TestRansomwareThreat:
    """
    Spec disqualifier: auto-replying to ransomware/security threats.
    msg_038 must never trigger an automated reply and must skip the LLM pipeline.
    """

    def test_security_flag_set(self):
        result = classify(**MSG_038)
        assert result.security_flag is True

    def test_skip_llm_pipeline(self):
        result = classify(**MSG_038)
        assert result.skip_llm_pipeline is True, (
            "Ransomware must bypass LLM/agent entirely — security team acts directly."
        )

    def test_suppress_auto_reply(self):
        result = classify(**MSG_038)
        assert result.suppress_auto_reply is True

    def test_max_priority(self):
        result = classify(**MSG_038)
        assert result.priority_score == PRIORITY_SECURITY_THREAT

    def test_category_is_security_not_spam(self):
        # Ransomware is checked BEFORE spam so it is never silently dropped.
        result = classify(**MSG_038)
        assert result.category == "Security"
        assert result.category != "Spam"

    def test_matched_rules_recorded(self):
        result = classify(**MSG_038)
        assert "ransomware_threat" in result.matched_rules

    def test_deterministic_route(self):
        result = classify(**MSG_038)
        assert result.deterministic_route is True


# ─── DISQUALIFIER: GDPR request misclassified as generic Inquiry ─────────────

class TestGDPRRequest:
    """
    Spec disqualifier: classifying the GDPR request as a generic 'Inquiry'.
    msg_052 must be category=Compliance, legal_flag=True, gdpr_flag=True,
    suppress_auto_reply=True, BUT skip_llm_pipeline=False (agent must run).
    """

    def test_gdpr_flag_set(self):
        result = classify(**MSG_052)
        assert result.gdpr_flag is True

    def test_legal_flag_set(self):
        result = classify(**MSG_052)
        assert result.legal_flag is True

    def test_category_is_compliance_not_inquiry(self):
        result = classify(**MSG_052)
        assert result.category == "Compliance", (
            f"GDPR request must be Compliance, got {result.category!r}. "
            "Classifying as 'Inquiry' is a spec disqualifier."
        )

    def test_suppress_auto_reply(self):
        # No generic auto-reply; agent produces a legally-compliant acknowledgement.
        result = classify(**MSG_052)
        assert result.suppress_auto_reply is True

    def test_does_not_skip_llm_pipeline(self):
        # Critical difference from spam/ransomware: GDPR MUST flow through the
        # agent so it can flag_for_legal + create compliance ticket.
        result = classify(**MSG_052)
        assert result.skip_llm_pipeline is False, (
            "GDPR request must NOT skip the pipeline — agent must produce "
            "acknowledgement + legal flag + compliance ticket."
        )

    def test_deterministic_route(self):
        result = classify(**MSG_052)
        assert result.deterministic_route is True

    def test_matched_rules_recorded(self):
        result = classify(**MSG_052)
        assert "gdpr_article_20" in result.matched_rules


# ─── DISQUALIFIER: Auto-replying to spam ─────────────────────────────────────

ALL_SPAM = [
    pytest.param(MSG_003, id="msg_003_seo_pitch"),
    pytest.param(MSG_024, id="msg_024_social_collab"),
    pytest.param(MSG_031, id="msg_031_nigerian_prince"),
    pytest.param(MSG_039, id="msg_039_cold_outreach"),
]


class TestSpam:
    """
    Spec disqualifier: auto-replying to spam.
    All four thread_spam_* emails must be suppress_auto_reply=True, skip_llm_pipeline=True.
    """

    @pytest.mark.parametrize("msg", ALL_SPAM)
    def test_suppress_auto_reply(self, msg):
        result = classify(**msg)
        assert result.suppress_auto_reply is True, (
            f"Spam from {msg['sender']!r} must never trigger an auto-reply."
        )

    @pytest.mark.parametrize("msg", ALL_SPAM)
    def test_skip_llm_pipeline(self, msg):
        result = classify(**msg)
        assert result.skip_llm_pipeline is True, (
            f"Spam from {msg['sender']!r} must skip the LLM pipeline."
        )

    @pytest.mark.parametrize("msg", ALL_SPAM)
    def test_category_is_spam(self, msg):
        result = classify(**msg)
        assert result.category == "Spam"

    @pytest.mark.parametrize("msg", ALL_SPAM)
    def test_lowest_priority(self, msg):
        result = classify(**msg)
        assert result.priority_score == PRIORITY_SPAM

    @pytest.mark.parametrize("msg", ALL_SPAM)
    def test_no_legal_or_security_flags(self, msg):
        result = classify(**msg)
        assert result.legal_flag is False
        assert result.security_flag is False
        assert result.gdpr_flag is False


# ─── Security alert (suspicious login — NOT ransomware) ──────────────────────

class TestSecurityAlert:
    """
    msg_016: suspicious login alert.
    Must route to security queue (security_flag=True) but MUST NOT skip the
    pipeline — the agent needs to investigate and notify the security team.
    """

    def test_security_flag_set(self):
        result = classify(**MSG_016)
        assert result.security_flag is True

    def test_suppress_auto_reply(self):
        result = classify(**MSG_016)
        assert result.suppress_auto_reply is True

    def test_does_not_skip_pipeline(self):
        result = classify(**MSG_016)
        assert result.skip_llm_pipeline is False

    def test_high_priority(self):
        result = classify(**MSG_016)
        assert result.priority_score == PRIORITY_SECURITY_ALERT

    def test_matched_rules_recorded(self):
        result = classify(**MSG_016)
        assert "security_alert" in result.matched_rules


# ─── Legal cease-and-desist ───────────────────────────────────────────────────

class TestCeaseDesist:
    """
    msg_020: "Cease and Desist Notice".
    Must suppress_auto_reply (legal team must review) but must NOT skip the
    pipeline (agent runs flag_for_legal + creates internal ticket).
    """

    def test_legal_flag_set(self):
        result = classify(**MSG_020)
        assert result.legal_flag is True

    def test_suppress_auto_reply(self):
        result = classify(**MSG_020)
        assert result.suppress_auto_reply is True

    def test_does_not_skip_pipeline(self):
        result = classify(**MSG_020)
        assert result.skip_llm_pipeline is False

    def test_high_priority(self):
        result = classify(**MSG_020)
        assert result.priority_score == PRIORITY_LEGAL_CEASEDESIST

    def test_matched_rules_recorded(self):
        result = classify(**MSG_020)
        assert "cease_and_desist" in result.matched_rules


# ─── Normal / legitimate emails ───────────────────────────────────────────────

class TestNormalEmails:

    def test_legitimate_pricing_inquiry_not_flagged(self):
        result = classify(**MSG_001)
        assert result.suppress_auto_reply is False
        assert result.skip_llm_pipeline is False
        assert result.gdpr_flag is False
        assert result.security_flag is False
        assert result.legal_flag is False
        assert result.category is None  # LLM decides

    def test_p0_urgency_boosts_priority(self):
        result = classify(**MSG_002)
        assert result.priority_score == PRIORITY_P0_INCIDENT
        assert result.priority_score > PRIORITY_NORMAL

    def test_p0_still_enters_pipeline(self):
        # Urgent customer emails MUST be processed by the LLM, not skipped.
        result = classify(**MSG_002)
        assert result.skip_llm_pipeline is False

    def test_urgency_matched_rule_recorded(self):
        result = classify(**MSG_002)
        assert "urgency_keywords" in result.matched_rules


# ─── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_empty_body_does_not_raise(self):
        result = classify(sender="test@example.com", subject="Hello", body="")
        assert isinstance(result, RuleEngineResult)

    def test_none_body_does_not_raise(self):
        result = classify(sender="test@example.com", subject="Hello", body=None)
        assert isinstance(result, RuleEngineResult)

    def test_whitespace_body_does_not_raise(self):
        result = classify(sender="test@example.com", subject="Hello", body="   \n\t  ")
        assert isinstance(result, RuleEngineResult)

    def test_none_subject_does_not_raise(self):
        result = classify(sender="test@example.com", subject=None, body="Hello")
        assert isinstance(result, RuleEngineResult)

    def test_to_dict_is_serialisable(self):
        import json
        result = classify(**MSG_038)
        serialised = result.to_dict()
        # Must not raise — this is stored in the emails.rule_flags JSON column.
        json.dumps(serialised)

    def test_ransomware_checked_before_spam(self):
        # A ransomware email that also matches spam patterns must be SECURITY,
        # not spam — the security team must see it.
        result = classify(
            sender="attacker@wealth-transfer.com",  # known spam domain
            subject="We have your data - Pay Now",
            body=(
                "We have exfiltrated your database. "
                "Send 2 BTC to wallet 1A2b3C4d5E6f within 48 hours "
                "or we publish the data on the dark web."
            ),
        )
        assert result.category == "Security"
        assert result.security_flag is True

    def test_gdpr_from_unknown_domain_still_caught(self):
        # GDPR requests can come from any domain — domain reputation must not block them.
        result = classify(
            sender="anyone@unknown-domain.xyz",
            subject="GDPR data portability request",
            body=(
                "Under GDPR Article 20, I am formally requesting a complete export "
                "of all personal data you hold about me within the statutory 30-day window."
            ),
        )
        assert result.gdpr_flag is True
        assert result.category == "Compliance"

    def test_internal_email_skips_pipeline(self):
        result = classify(
            sender="hr@internal.com",
            subject="Company All-Hands + Holiday Party",
            body="Reminder: All-hands is Thursday 3pm.",
        )
        assert result.skip_llm_pipeline is True
        assert result.category == "Internal"
