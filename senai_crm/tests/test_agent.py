"""
Phase 4 agent tests.

Mandatory test: run the full agent on msg_060 (bob_outage escalation).
The trace must show:
  thread history retrieval → SLA policy search → account status check →
  legal threat recognition → flag_for_legal → holding reply draft →
  escalate_to_human.

Tests:
  TestBobOutageTrace  — 6-step scripted trace matches expected actions
  TestCriticalSafetyGate — send_auto_reply on Critical email is blocked
  TestDryRun          — dry-run produces trace but no Action rows in DB
"""

import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.database import Base
from app.models.contact import Contact
from app.models.email import Email
from app.models.action import Action
from app.models.enums import ContactStatus, EmailStatus
from app.models.thread import Thread
from app.schemas.agent import AgentRunResult
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.rag_service import RagService


# ─── FakeAgentLLM ─────────────────────────────────────────────────────────────

class FakeAgentLLM:
    """
    Scripted queue-based fake. Returns pre-defined JSON tool-call responses
    in order, making the ReAct loop fully deterministic without any real LLM.
    """

    def __init__(self, steps: list[dict]) -> None:
        self._queue = [json.dumps(s) for s in steps]
        self.call_count = 0

    def generate(self, prompt: str) -> str:
        self.call_count += 1
        if not self._queue:
            raise RuntimeError("FakeAgentLLM exhausted — more steps called than scripted")
        return self._queue.pop(0)


# ─── Scripted steps for bob_outage (msg_060) ──────────────────────────────────

BOB_OUTAGE_STEPS = [
    {
        "thought": "This email is about an SLA breach and mentions legal involvement. I need to understand the thread history first.",
        "action": "get_thread_history",
        "action_input": {"thread_id": "thread_bob_outage"},
    },
    {
        "thought": "Thread shows 47-minute P0 outage and prior SLA discussion. Let me search the knowledge base for SLA policy obligations.",
        "action": "search_knowledge_base",
        "action_input": {"query": "SLA breach credit outage root cause analysis obligation"},
    },
    {
        "thought": "I have the SLA policy context. Now I need to check Bob's account status and churn risk.",
        "action": "check_account_status",
        "action_input": {"email": "bob.jones@enterprise.net"},
    },
    {
        "thought": "High-value account ($15K/mo) with churn_risk=0.87. The email explicitly states legal team involvement. I must flag this for legal review.",
        "action": "flag_for_legal",
        "action_input": {
            "reason": (
                "Customer explicitly states legal team involvement and threatens formal correspondence. "
                "SLA breach context: 47-minute P0 outage on 2023-10-01. "
                "Renewal placed on hold pending resolution."
            )
        },
    },
    {
        "thought": "Legal flag set. I should draft a holding reply acknowledging receipt before escalating.",
        "action": "draft_reply",
        "action_input": {
            "content": (
                "Dear Bob, thank you for your follow-up. We take your concerns very seriously and have "
                "escalated this matter to our senior support team and legal counsel. "
                "We will respond within 24 hours with a formal resolution plan. "
                "We sincerely apologize for the service disruption and its impact on your operations."
            )
        },
    },
    {
        "thought": "Legal team is involved, SLA breach confirmed, account is at high churn risk. This must be escalated to a human agent immediately.",
        "action": "escalate_to_human",
        "action_input": {
            "reason": "Legal team involvement + SLA breach + Critical urgency + $15K account churn risk",
            "brief": (
                "Bob Jones (Enterprise Corp, $15K/mo, churn_risk=0.87) has escalated the Oct 2023 P0 outage "
                "to legal. Renewal is on hold. Requires senior escalation and legal review within 24h. "
                "Holding reply drafted."
            ),
        },
    },
]


# ─── DB fixture ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def module_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def module_session(module_engine):
    Session = sessionmaker(bind=module_engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed_bob_outage(db) -> int:
    """
    Seed the bob_outage thread: contact, thread, msg_002, msg_009, msg_060.
    Returns the email_id of msg_060 (the trigger email for the agent).
    """
    contact = Contact(
        email="bob.jones@enterprise.net",
        name="Bob Jones",
        company="Enterprise Corp",
        status=ContactStatus.ACTIVE,
        account_value=15000.0,
        churn_risk_score=0.87,
    )
    db.add(contact)
    db.flush()

    thread = Thread(
        thread_id="thread_bob_outage",
        subject="URGENT: Production System Down",
        sender_email="bob.jones@enterprise.net",
        contact_id=contact.id,
        first_seen_at=datetime(2023, 10, 1, 9, 15, tzinfo=timezone.utc),
        last_updated_at=datetime(2023, 10, 19, 14, 0, tzinfo=timezone.utc),
    )
    db.add(thread)
    db.flush()

    msg_002 = Email(
        thread_id=thread.id,
        message_id="msg_002",
        sender="bob.jones@enterprise.net",
        subject="URGENT: Production System Down",
        body=(
            "Our production system is completely down. We are losing $10,000 per minute. "
            "This is a P0 incident. Please escalate immediately. "
            "We need an ETA for resolution or I will be forced to escalate to your CEO."
        ),
        timestamp=datetime(2023, 10, 1, 9, 15, tzinfo=timezone.utc),
        status=EmailStatus.ESCALATED,
        urgency="Critical",
        category="Technical",
    )
    db.add(msg_002)

    msg_009 = Email(
        thread_id=thread.id,
        message_id="msg_009",
        sender="bob.jones@enterprise.net",
        subject="Re: URGENT: Production System Down",
        body=(
            "The downtime lasted 47 minutes. We expect full SLA credit for this incident. "
            "Additionally, we require a comprehensive 24-hour root cause analysis. "
            "If we do not receive this within 24 hours, we will begin evaluating alternative vendors."
        ),
        timestamp=datetime(2023, 10, 3, 10, 0, tzinfo=timezone.utc),
        status=EmailStatus.ESCALATED,
        urgency="Critical",
        category="Technical",
    )
    db.add(msg_009)

    msg_060 = Email(
        thread_id=thread.id,
        message_id="msg_060",
        sender="bob.jones@enterprise.net",
        subject="Escalation: SLA Breach + Legal Review",
        body=(
            "Following up on the unresolved P0 outage from October 1st. "
            "Our legal team is now involved. Please expect formal correspondence. "
            "We are also putting the renewal on hold pending resolution."
        ),
        timestamp=datetime(2023, 10, 19, 14, 0, tzinfo=timezone.utc),
        status=EmailStatus.PROCESSING,
        urgency="Critical",
        category="Legal",
        rule_flags={"legal_flag": False},
    )
    db.add(msg_060)
    db.flush()
    db.commit()

    return msg_060.id


# ─── TestBobOutageTrace ───────────────────────────────────────────────────────

class TestBobOutageTrace:
    """Mandatory trace test: full 6-step agent run on the bob_outage escalation."""

    @pytest.fixture(scope="class", autouse=True)
    def run_agent(self, module_session):
        msg_060_id = _seed_bob_outage(module_session)

        llm = FakeAgentLLM(BOB_OUTAGE_STEPS)
        rag = RagService()  # empty index — tools don't need it for this trace
        orchestrator = AgentOrchestrator(llm_client=llm, rag_service=rag, db=module_session)
        result = orchestrator.run(msg_060_id, dry_run=False)

        self.__class__.result = result
        self.__class__.email_id = msg_060_id
        self.__class__.db = module_session

    def test_step_count_is_6(self):
        assert len(self.result.steps) == 6, (
            f"Expected 6 steps, got {len(self.result.steps)}"
        )

    def test_step_1_is_thread_history(self):
        assert self.result.steps[0].action == "get_thread_history"

    def test_step_2_is_search_kb(self):
        assert self.result.steps[1].action == "search_knowledge_base"

    def test_step_3_is_account_status(self):
        assert self.result.steps[2].action == "check_account_status"

    def test_step_4_is_flag_for_legal(self):
        assert self.result.steps[3].action == "flag_for_legal"

    def test_step_5_is_draft_reply(self):
        assert self.result.steps[4].action == "draft_reply"

    def test_step_6_is_escalate_to_human(self):
        assert self.result.steps[5].action == "escalate_to_human"

    def test_final_action_is_escalate(self):
        assert self.result.final_action == "escalate_to_human"

    def test_legal_flag_set_on_email(self):
        email_row = self.db.query(Email).filter(Email.id == self.email_id).first()
        self.db.refresh(email_row)
        assert email_row.rule_flags.get("legal_flag") is True, (
            "flag_for_legal must set email.rule_flags['legal_flag'] = True"
        )

    def test_email_status_escalated(self):
        email_row = self.db.query(Email).filter(Email.id == self.email_id).first()
        self.db.refresh(email_row)
        assert email_row.status == EmailStatus.ESCALATED

    def test_action_row_persisted_with_reasoning_log(self):
        actions = (
            self.db.query(Action)
            .filter(Action.email_id == self.email_id)
            .all()
        )
        # At least one ESCALATE action
        escalate_actions = [a for a in actions if a.action_type.value == "Escalate"]
        assert escalate_actions, "An ESCALATE Action row must be persisted"

        log = escalate_actions[0].agent_reasoning_log
        assert log is not None
        assert len(log) == 6, f"Reasoning log must have 6 steps, got {len(log)}"

    def test_reasoning_log_structure(self):
        actions = (
            self.db.query(Action)
            .filter(Action.email_id == self.email_id)
            .all()
        )
        escalate_actions = [a for a in actions if a.action_type.value == "Escalate"]
        log = escalate_actions[0].agent_reasoning_log
        for entry in log:
            assert "step" in entry
            assert "thought" in entry
            assert "action" in entry
            assert "observation" in entry


# ─── TestCriticalSafetyGate ───────────────────────────────────────────────────

class TestCriticalSafetyGate:
    """Verify that send_auto_reply on a Critical email is blocked."""

    @pytest.fixture()
    def db_session(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        session = Session()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()

    def test_send_auto_reply_blocked_for_critical(self, db_session):
        contact = Contact(
            email="critical@example.com",
            status=ContactStatus.ACTIVE,
        )
        db_session.add(contact)
        db_session.flush()

        thread = Thread(
            thread_id="thread_critical_test",
            subject="Critical test",
            sender_email="critical@example.com",
            contact_id=contact.id,
            first_seen_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            last_updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        db_session.add(thread)
        db_session.flush()

        email_row = Email(
            thread_id=thread.id,
            message_id="msg_critical_test",
            sender="critical@example.com",
            subject="CRITICAL ISSUE",
            body="This is a critical issue.",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            status=EmailStatus.PROCESSING,
            urgency="Critical",
        )
        db_session.add(email_row)
        db_session.flush()
        db_session.commit()

        scripted = [
            {
                "thought": "I will send an auto-reply.",
                "action": "send_auto_reply",
                "action_input": {"content": "Thank you for your message."},
            }
        ]
        llm = FakeAgentLLM(scripted)
        rag = RagService()
        orchestrator = AgentOrchestrator(llm_client=llm, rag_service=rag, db=db_session)
        result = orchestrator.run(email_row.id, dry_run=False)

        assert result.final_action == "critical_safety_escalated", (
            f"Expected critical_safety_escalated, got {result.final_action}"
        )
        assert "SAFETY GATE" in result.steps[-1].observation


# ─── TestDryRun ───────────────────────────────────────────────────────────────

class TestDryRun:
    """Dry-run produces a trace but writes no Action rows to the DB."""

    @pytest.fixture()
    def db_session(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        session = Session()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()

    def test_dry_run_no_action_rows(self, db_session):
        contact = Contact(
            email="dryrun@example.com",
            status=ContactStatus.ACTIVE,
        )
        db_session.add(contact)
        db_session.flush()

        thread = Thread(
            thread_id="thread_dryrun",
            subject="Dry run test",
            sender_email="dryrun@example.com",
            contact_id=contact.id,
            first_seen_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            last_updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        db_session.add(thread)
        db_session.flush()

        email_row = Email(
            thread_id=thread.id,
            message_id="msg_dryrun",
            sender="dryrun@example.com",
            subject="Test dry run",
            body="I need a refund.",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            status=EmailStatus.PROCESSING,
            urgency="Low",
        )
        db_session.add(email_row)
        db_session.flush()
        db_session.commit()

        scripted = [
            {
                "thought": "I'll escalate this.",
                "action": "escalate_to_human",
                "action_input": {"reason": "test escalation", "brief": "dry run test"},
            }
        ]
        llm = FakeAgentLLM(scripted)
        rag = RagService()
        orchestrator = AgentOrchestrator(llm_client=llm, rag_service=rag, db=db_session)
        result = orchestrator.run(email_row.id, dry_run=True)

        assert result.dry_run is True
        assert result.final_action == "escalate_to_human"

        # No Action rows should have been created
        actions = db_session.query(Action).filter(Action.email_id == email_row.id).all()
        assert actions == [], f"Dry-run must not write Action rows, found: {actions}"

    def test_dry_run_observation_prefixed(self, db_session):
        contact = Contact(
            email="dryrun2@example.com",
            status=ContactStatus.ACTIVE,
        )
        db_session.add(contact)
        db_session.flush()

        thread = Thread(
            thread_id="thread_dryrun2",
            subject="Dry run test 2",
            sender_email="dryrun2@example.com",
            contact_id=contact.id,
            first_seen_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            last_updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        db_session.add(thread)
        db_session.flush()

        email_row = Email(
            thread_id=thread.id,
            message_id="msg_dryrun2",
            sender="dryrun2@example.com",
            subject="Test",
            body="Test body",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            status=EmailStatus.PROCESSING,
            urgency="Low",
        )
        db_session.add(email_row)
        db_session.flush()
        db_session.commit()

        scripted = [
            {
                "thought": "Draft a reply first.",
                "action": "draft_reply",
                "action_input": {"content": "Hello, we received your message."},
            },
            {
                "thought": "Now escalate.",
                "action": "escalate_to_human",
                "action_input": {"reason": "needs review", "brief": "dry run"},
            },
        ]
        llm = FakeAgentLLM(scripted)
        rag = RagService()
        orchestrator = AgentOrchestrator(llm_client=llm, rag_service=rag, db=db_session)
        result = orchestrator.run(email_row.id, dry_run=True)

        draft_step = next(s for s in result.steps if s.action == "draft_reply")
        assert "[DRY-RUN]" in draft_step.observation
