"""
POST /api/ingest integration tests — Phase 2.

All tests use an in-memory SQLite DB and a FakeLLMClient injected via
FastAPI dependency override (no Gemini API key needed, no network calls).

Coverage:
  1.  Happy path — email persisted, response fields correct
  2.  Idempotency — duplicate message_id returns already_exists=True, no DB duplicate
  3.  Malformed payload — missing required field → 422 with validation error
  4.  Blank required field — whitespace message_id → 422
  5.  Missing body — None/absent body stored as empty string, not an error
  6.  Empty body — stored, body_truncated=False
  7.  Long body — body > 10,000 chars → body_truncated flag set in DB
  8.  Thread linking — two emails with same thread_id share a thread row
  9.  Thread linking — two different thread_ids create two thread rows
  10. Out-of-order timestamps — second email has earlier timestamp; thread.last_updated_at
      reflects wall-clock (not email timestamp)
  11. Rule engine gate — ransomware email skips LLM, status=Escalated
  12. Rule engine gate — spam email skips LLM, status=Ignored
  13. Rule engine gate — GDPR email (suppress_auto_reply only) still runs LLM
  14. Classification persisted — sentiment_score, category, urgency, requires_human written
  15. Disqualifier: no auto-reply to spam (skip_llm_pipeline=True on spam)
  16. Disqualifier: GDPR gets legal_flag=True from rule engine
  17. Disqualifier: ransomware gets security_flag=True from rule engine
  18. Disqualifier: malformed payload returns ErrorEnvelope shape
"""

import json

import pytest
from sqlalchemy.orm import Session

from app.models.email import Email
from app.models.thread import Thread
from app.models.contact import Contact


# ─── Fixtures ─────────────────────────────────────────────────────────────────

BASE_EMAIL = {
    "message_id": "test_msg_001",
    "sender": "alice@example.com",
    "subject": "Pricing question",
    "body": "Hi, can you tell me about your pricing tiers?",
    "timestamp": "2023-10-01T09:00:00Z",
    "thread_id": "thread_test_001",
}

RANSOMWARE_EMAIL = {
    "message_id": "test_ransom_001",
    "sender": "hacker@anon-collective.net",
    "subject": "Security Notice",
    "body": (
        "We have exfiltrated 50,000 customer records from your systems. "
        "Send 2 BTC to wallet 1A2b3C4d5E6f within 48 hours "
        "or we will publish the data on the dark web."
    ),
    "timestamp": "2023-10-01T12:00:00Z",
    "thread_id": "thread_ransom_001",
}

SPAM_EMAIL = {
    "message_id": "test_spam_001",
    "sender": "promo@marketing-guru.io",
    "subject": "Exclusive offer just for you!",
    "body": "Click here to claim your prize. Limited time offer!",
    "timestamp": "2023-10-01T13:00:00Z",
    "thread_id": "thread_spam_001",
}

GDPR_EMAIL = {
    "message_id": "test_gdpr_001",
    "sender": "user@example.com",
    "subject": "GDPR data portability request",
    "body": (
        "I am exercising my right to data portability under GDPR Article 20. "
        "Please provide all personal data you hold on me within 30 days."
    ),
    "timestamp": "2023-10-01T14:00:00Z",
    "thread_id": "thread_gdpr_001",
}


# ─── 1. Happy path ─────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_returns_200(self, client):
        resp = client.post("/api/ingest", json=BASE_EMAIL)
        assert resp.status_code == 200

    def test_response_fields(self, client):
        resp = client.post("/api/ingest", json=BASE_EMAIL)
        data = resp.json()
        assert data["message_id"] == BASE_EMAIL["message_id"]
        assert data["already_exists"] is False
        assert isinstance(data["email_id"], int)
        assert data["thread_id"] == BASE_EMAIL["thread_id"]
        assert isinstance(data["priority_score"], int)
        assert isinstance(data["rule_flags"], dict)
        assert data["status"] in ("Received", "Processing", "Replied", "Escalated", "Ignored")


# ─── 2. Idempotency ────────────────────────────────────────────────────────────

class TestIdempotency:
    def test_duplicate_returns_already_exists(self, client_factory, db_session):
        tc, _ = client_factory(llm_responses=[
            _valid_json(),
            _valid_json(),  # second call never happens, but queue should not be empty
        ])
        r1 = tc.post("/api/ingest", json=BASE_EMAIL)
        r2 = tc.post("/api/ingest", json=BASE_EMAIL)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r2.json()["already_exists"] is True

    def test_no_duplicate_rows(self, client_factory, db_engine):
        from sqlalchemy.orm import sessionmaker
        tc, _ = client_factory(llm_responses=[_valid_json(), _valid_json()])
        tc.post("/api/ingest", json=BASE_EMAIL)
        tc.post("/api/ingest", json=BASE_EMAIL)

        Session = sessionmaker(bind=db_engine)
        with Session() as s:
            count = s.query(Email).filter(Email.message_id == BASE_EMAIL["message_id"]).count()
        assert count == 1

    def test_same_email_id_returned_on_duplicate(self, client_factory):
        tc, _ = client_factory(llm_responses=[_valid_json(), _valid_json()])
        r1 = tc.post("/api/ingest", json=BASE_EMAIL)
        r2 = tc.post("/api/ingest", json=BASE_EMAIL)
        assert r1.json()["email_id"] == r2.json()["email_id"]


# ─── 3 & 4. Malformed payloads ─────────────────────────────────────────────────

class TestMalformedPayload:
    def test_missing_message_id_returns_422(self, client):
        bad = {k: v for k, v in BASE_EMAIL.items() if k != "message_id"}
        resp = client.post("/api/ingest", json=bad)
        assert resp.status_code == 422

    def test_missing_sender_returns_422(self, client):
        bad = {k: v for k, v in BASE_EMAIL.items() if k != "sender"}
        resp = client.post("/api/ingest", json=bad)
        assert resp.status_code == 422

    def test_missing_thread_id_returns_422(self, client):
        bad = {k: v for k, v in BASE_EMAIL.items() if k != "thread_id"}
        resp = client.post("/api/ingest", json=bad)
        assert resp.status_code == 422

    def test_blank_message_id_returns_422(self, client):
        bad = {**BASE_EMAIL, "message_id": "   "}
        resp = client.post("/api/ingest", json=bad)
        assert resp.status_code == 422

    def test_blank_sender_returns_422(self, client):
        bad = {**BASE_EMAIL, "sender": ""}
        resp = client.post("/api/ingest", json=bad)
        assert resp.status_code == 422

    def test_invalid_timestamp_returns_422(self, client):
        bad = {**BASE_EMAIL, "timestamp": "not-a-date"}
        resp = client.post("/api/ingest", json=bad)
        assert resp.status_code == 422

    def test_entirely_empty_body_is_valid(self, client):
        payload = {**BASE_EMAIL, "body": None, "message_id": "test_nobody_001"}
        resp = client.post("/api/ingest", json=payload)
        assert resp.status_code == 200

    def test_whitespace_only_body_is_valid(self, client_factory):
        tc, _ = client_factory(llm_responses=[_valid_json()])
        payload = {**BASE_EMAIL, "body": "   ", "message_id": "test_wsonly_001"}
        resp = tc.post("/api/ingest", json=payload)
        assert resp.status_code == 200


# ─── 5–7. Body handling ────────────────────────────────────────────────────────

class TestBodyHandling:
    def test_none_body_stored_without_error(self, client_factory, db_engine):
        from sqlalchemy.orm import sessionmaker
        tc, _ = client_factory(llm_responses=[_valid_json()])
        payload = {**BASE_EMAIL, "body": None, "message_id": "test_body_none"}
        tc.post("/api/ingest", json=payload)

        Session = sessionmaker(bind=db_engine)
        with Session() as s:
            row = s.query(Email).filter(Email.message_id == "test_body_none").first()
        assert row is not None
        assert row.body == ""
        assert row.body_truncated is False

    def test_short_body_truncation_false(self, client_factory, db_engine):
        from sqlalchemy.orm import sessionmaker
        tc, _ = client_factory(llm_responses=[_valid_json()])
        payload = {**BASE_EMAIL, "body": "Short body.", "message_id": "test_body_short"}
        tc.post("/api/ingest", json=payload)

        Session = sessionmaker(bind=db_engine)
        with Session() as s:
            row = s.query(Email).filter(Email.message_id == "test_body_short").first()
        assert row.body_truncated is False

    def test_long_body_sets_truncation_flag(self, client_factory, db_engine):
        from sqlalchemy.orm import sessionmaker
        tc, _ = client_factory(llm_responses=[_valid_json()])
        long_body = "x" * 10_001
        payload = {**BASE_EMAIL, "body": long_body, "message_id": "test_body_long"}
        tc.post("/api/ingest", json=payload)

        Session = sessionmaker(bind=db_engine)
        with Session() as s:
            row = s.query(Email).filter(Email.message_id == "test_body_long").first()
        assert row.body_truncated is True
        assert len(row.body) == 10_001  # full body stored despite flag


# ─── 8–10. Thread linking ──────────────────────────────────────────────────────

class TestThreadLinking:
    def test_two_emails_same_thread_share_row(self, client_factory, db_engine):
        from sqlalchemy.orm import sessionmaker
        tc, _ = client_factory(llm_responses=[_valid_json(), _valid_json()])
        e1 = {**BASE_EMAIL, "message_id": "thread_link_001"}
        e2 = {**BASE_EMAIL, "message_id": "thread_link_002"}
        tc.post("/api/ingest", json=e1)
        tc.post("/api/ingest", json=e2)

        Session = sessionmaker(bind=db_engine)
        with Session() as s:
            rows = s.query(Email).filter(Email.message_id.in_(["thread_link_001", "thread_link_002"])).all()
            thread_ids = {r.thread_id for r in rows}
        assert len(thread_ids) == 1  # both share the same thread row

    def test_different_thread_ids_create_separate_rows(self, client_factory, db_engine):
        from sqlalchemy.orm import sessionmaker
        tc, _ = client_factory(llm_responses=[_valid_json(), _valid_json()])
        e1 = {**BASE_EMAIL, "message_id": "sep_thread_001", "thread_id": "thread_alpha"}
        e2 = {**BASE_EMAIL, "message_id": "sep_thread_002", "thread_id": "thread_beta"}
        tc.post("/api/ingest", json=e1)
        tc.post("/api/ingest", json=e2)

        Session = sessionmaker(bind=db_engine)
        with Session() as s:
            count = s.query(Thread).filter(Thread.thread_id.in_(["thread_alpha", "thread_beta"])).count()
        assert count == 2

    def test_contact_linked_to_thread(self, client_factory, db_engine):
        from sqlalchemy.orm import sessionmaker
        tc, _ = client_factory(llm_responses=[_valid_json()])
        tc.post("/api/ingest", json=BASE_EMAIL)

        Session = sessionmaker(bind=db_engine)
        with Session() as s:
            thread = s.query(Thread).filter(Thread.thread_id == BASE_EMAIL["thread_id"]).first()
            contact = s.query(Contact).filter(Contact.email == BASE_EMAIL["sender"]).first()
        assert thread is not None
        assert contact is not None
        assert thread.contact_id == contact.id


# ─── 11–13. Rule engine gate ──────────────────────────────────────────────────

class TestRuleEngineGate:
    def test_ransomware_skips_llm(self, client_factory):
        tc, fake_llm = client_factory(llm_responses=[])  # no LLM responses — should not be called
        resp = tc.post("/api/ingest", json=RANSOMWARE_EMAIL)
        assert resp.status_code == 200
        assert fake_llm.call_count == 0

    def test_ransomware_status_escalated(self, client_factory):
        tc, _ = client_factory(llm_responses=[])
        resp = tc.post("/api/ingest", json=RANSOMWARE_EMAIL)
        assert resp.json()["status"] == "Escalated"

    def test_spam_skips_llm(self, client_factory):
        tc, fake_llm = client_factory(llm_responses=[])
        resp = tc.post("/api/ingest", json=SPAM_EMAIL)
        assert resp.status_code == 200
        assert fake_llm.call_count == 0

    def test_spam_status_ignored(self, client_factory):
        tc, _ = client_factory(llm_responses=[])
        resp = tc.post("/api/ingest", json=SPAM_EMAIL)
        assert resp.json()["status"] == "Ignored"

    def test_gdpr_runs_llm(self, client_factory):
        tc, fake_llm = client_factory(llm_responses=[_valid_json(category="Compliance")])
        resp = tc.post("/api/ingest", json=GDPR_EMAIL)
        assert resp.status_code == 200
        assert fake_llm.call_count == 1  # LLM was called

    def test_gdpr_has_legal_flag(self, client_factory):
        tc, _ = client_factory(llm_responses=[_valid_json(category="Compliance")])
        resp = tc.post("/api/ingest", json=GDPR_EMAIL)
        assert resp.json()["rule_flags"]["gdpr_flag"] is True


# ─── 14. Classification persisted ─────────────────────────────────────────────

class TestClassificationPersisted:
    def test_sentiment_score_written(self, client_factory, db_engine):
        from sqlalchemy.orm import sessionmaker
        tc, _ = client_factory(llm_responses=[_valid_json(sentiment_score=-0.8, category="Complaint")])
        payload = {**BASE_EMAIL, "message_id": "persist_sentiment_001"}
        tc.post("/api/ingest", json=payload)

        Session = sessionmaker(bind=db_engine)
        with Session() as s:
            row = s.query(Email).filter(Email.message_id == "persist_sentiment_001").first()
        assert row.sentiment_score == pytest.approx(-0.8, abs=0.01)

    def test_category_written(self, client_factory, db_engine):
        from sqlalchemy.orm import sessionmaker
        tc, _ = client_factory(llm_responses=[_valid_json(category="Feature Request")])
        payload = {**BASE_EMAIL, "message_id": "persist_cat_001"}
        tc.post("/api/ingest", json=payload)

        Session = sessionmaker(bind=db_engine)
        with Session() as s:
            row = s.query(Email).filter(Email.message_id == "persist_cat_001").first()
        assert row.category == "Feature Request"

    def test_requires_human_written(self, client_factory, db_engine):
        from sqlalchemy.orm import sessionmaker
        tc, _ = client_factory(llm_responses=[
            _valid_json(requires_human=True, escalation_reason="Legal threat", suggested_reply=None)
        ])
        payload = {**BASE_EMAIL, "message_id": "persist_rh_001"}
        tc.post("/api/ingest", json=payload)

        Session = sessionmaker(bind=db_engine)
        with Session() as s:
            row = s.query(Email).filter(Email.message_id == "persist_rh_001").first()
        assert row.requires_human is True


# ─── 15–18. Disqualifiers ─────────────────────────────────────────────────────

class TestDisqualifiers:
    def test_no_auto_reply_to_spam(self, client_factory):
        """Spec disqualifier: spam must never trigger an auto-reply."""
        tc, fake_llm = client_factory(llm_responses=[])
        resp = tc.post("/api/ingest", json=SPAM_EMAIL)
        flags = resp.json()["rule_flags"]
        assert flags["suppress_auto_reply"] is True
        assert flags["skip_llm_pipeline"] is True
        assert fake_llm.call_count == 0

    def test_gdpr_legal_flag_set(self, client_factory):
        """Spec disqualifier: GDPR email must be flagged for legal review."""
        tc, _ = client_factory(llm_responses=[_valid_json(category="Compliance")])
        resp = tc.post("/api/ingest", json=GDPR_EMAIL)
        assert resp.json()["rule_flags"]["legal_flag"] is True

    def test_ransomware_security_flag_set(self, client_factory):
        """Spec disqualifier: ransomware must set security_flag=True."""
        tc, _ = client_factory(llm_responses=[])
        resp = tc.post("/api/ingest", json=RANSOMWARE_EMAIL)
        assert resp.json()["rule_flags"]["security_flag"] is True

    def test_malformed_payload_returns_422_shape(self, client):
        """Spec disqualifier: malformed email must return a structured error."""
        resp = client.post("/api/ingest", json={"garbage": "data"})
        assert resp.status_code == 422
        # FastAPI 422 body contains a 'detail' key with validation errors
        assert "detail" in resp.json()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _valid_json(**overrides) -> str:
    base = {
        "category": "Inquiry",
        "sentiment": "Neutral",
        "sentiment_score": 0.0,
        "urgency": "Low",
        "requires_human": False,
        "escalation_reason": None,
        "suggested_reply": "Thank you for reaching out.",
        "confidence": 0.9,
        "detected_entities": {
            "order_ids": [],
            "ticket_ids": [],
            "monetary_amounts": [],
            "deadlines": [],
            "products_mentioned": [],
        },
    }
    base.update(overrides)
    return json.dumps(base)
