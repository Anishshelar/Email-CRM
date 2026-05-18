"""
Shared pytest fixtures for all test modules.

Provides:
  - in-memory SQLite engine (fresh per test)
  - FastAPI TestClient with the LLM dependency overridden to a FakeLLMClient
"""

import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # ensure all ORM models are registered on Base.metadata
from app.database import Base, get_db
from app.main import app
from app.api.ingest import _get_classification_service
from app.services.classification_service import ClassificationService


# ─── In-memory database ────────────────────────────────────────────────────────

@pytest.fixture()
def db_engine():
    # StaticPool ensures all connections share the same in-memory SQLite instance.
    # Without it, each new connection (TestClient creates one per request) gets
    # an empty DB because `:memory:` databases are connection-scoped in SQLite.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    TestingSessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


# ─── Fake LLM client ──────────────────────────────────────────────────────────

class FakeLLMClient:
    """Queue-based fake — returns responses in order, tracks call count."""

    def __init__(self, responses: list[str]) -> None:
        self._queue = list(responses)
        self.call_count = 0

    def generate(self, prompt: str) -> str:
        self.call_count += 1
        if not self._queue:
            raise RuntimeError("FakeLLMClient exhausted")
        return self._queue.pop(0)


def _valid_classification_json(**overrides) -> str:
    base = {
        "category": "Inquiry",
        "sentiment": "Neutral",
        "sentiment_score": 0.0,
        "urgency": "Low",
        "requires_human": False,
        "escalation_reason": None,
        "suggested_reply": "Thank you for reaching out. We'll look into this.",
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


# ─── TestClient with overrides ────────────────────────────────────────────────

@pytest.fixture()
def client_factory(db_engine):
    """
    Returns a factory: call it with a list of LLM response strings to get a
    TestClient that uses an in-memory DB and the fake LLM.
    """
    def _make(llm_responses: list[str] | None = None):
        if llm_responses is None:
            llm_responses = [_valid_classification_json()]

        fake_llm = FakeLLMClient(llm_responses)
        svc = ClassificationService(fake_llm)

        TestingSessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

        def override_db():
            session = TestingSessionLocal()
            try:
                yield session
            finally:
                session.close()

        def override_svc():
            return svc

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[_get_classification_service] = override_svc

        tc = TestClient(app, raise_server_exceptions=True)
        return tc, fake_llm

    yield _make

    # Clean up overrides after the test
    app.dependency_overrides.clear()


@pytest.fixture()
def client(client_factory):
    """Simple fixture: one valid LLM response, no special setup needed."""
    tc, _ = client_factory()
    return tc
