"""
AgentOrchestrator — Phase 4.

Implements a ReAct (Reason + Act) loop over a fixed set of tools to process
customer emails autonomously. The agent:
  1. Receives an email_id.
  2. Runs a Thought → Action → Observation loop (max MAX_STEPS iterations).
  3. Persists the full reasoning trace to actions.agent_reasoning_log.
  4. Returns an AgentRunResult with the trace and final action taken.

Safety rules (deterministic, never LLM-dependent):
  - emails with urgency=Critical are NEVER auto-replied. The safety gate
    intercepts any send_auto_reply call and forces escalate_to_human.
  - When MAX_STEPS is reached without a terminal action, the agent auto-escalates
    with a summary of the reasoning so far.

Dry-run mode:
  - Read-only tools (search_kb, thread_history, contact_profile, account_status)
    execute fully and return real data.
  - Write tools (draft_reply, escalate, create_ticket, flag_legal, send_auto_reply)
    skip DB side-effects and return [DRY-RUN] observations.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.action import Action
from app.models.email import Email
from app.models.enums import ActionType, EmailStatus
from app.models.thread import Thread
from app.models.contact import Contact
from app.schemas.agent import AgentRunResult, AgentStep
from app.services.rag_service import RagService
from app.services.llm_client import LLMClientProtocol
from app.services.web_intelligence_service import WebIntelligenceService, should_trigger_web_intelligence

logger = logging.getLogger(__name__)

MAX_STEPS = 6
TERMINAL_ACTIONS = {"escalate_to_human", "send_auto_reply", "FINISH"}

# ── Agent prompt components ────────────────────────────────────────────────────

_AGENT_SYSTEM = """\
You are an AI customer support agent. Your job is to process a customer email \
by reasoning step-by-step and calling tools as needed.

Respond with a single JSON object (no markdown, no extra text):
{"thought": "<your reasoning>", "action": "<tool_name>", "action_input": {<args>}}

When you are done, use action "FINISH" with action_input {"summary": "<brief>"}.
"""

_TOOL_SPEC = """\
Available tools:
- search_knowledge_base(query: str) → retrieves relevant KB chunks
- get_thread_history(thread_id: str) → prior emails in this thread
- get_contact_profile(email: str) → contact record (account_value, churn_risk)
- check_account_status(email: str) → account status and risk indicators
- draft_reply(content: str) → stage a reply draft (does not send)
- escalate_to_human(reason: str, brief: str) → [TERMINAL] hands off to human agent
- create_internal_ticket(title: str, description: str) → creates a support ticket
- flag_for_legal(reason: str) → [TERMINAL-SIDE-EFFECT] flags email for legal review
- send_auto_reply(content: str) → [TERMINAL] sends the staged reply automatically
- scrape_public_sentiment(company: str) → mock public sentiment data (Phase 5 stub)
"""


class AgentOrchestrator:
    def __init__(
        self,
        llm_client: LLMClientProtocol,
        rag_service: RagService,
        db: Session,
    ) -> None:
        self._llm = llm_client
        self._rag = rag_service
        self._db = db

    # ── Public entry point ─────────────────────────────────────────────────────

    def run(self, email_id: int, dry_run: bool = False) -> AgentRunResult:
        email_row = self._db.query(Email).filter(Email.id == email_id).first()
        if email_row is None:
            raise ValueError(f"Email {email_id} not found")

        thread = self._db.query(Thread).filter(Thread.id == email_row.thread_id).first()
        is_critical = (email_row.urgency or "").lower() == "critical"

        steps: list[AgentStep] = []
        draft_content: Optional[str] = None

        prompt_prefix = self._build_prompt_prefix(email_row, thread, is_critical)

        for step_num in range(1, MAX_STEPS + 1):
            prompt = self._build_prompt(prompt_prefix, steps)
            raw = self._llm.generate(prompt)

            try:
                parsed = json.loads(raw)
                thought = str(parsed.get("thought", ""))
                action = str(parsed.get("action", "FINISH"))
                action_input = parsed.get("action_input", {})
                if not isinstance(action_input, dict):
                    action_input = {}
            except (json.JSONDecodeError, TypeError):
                thought = "Failed to parse LLM response."
                action = "escalate_to_human"
                action_input = {
                    "reason": "Agent produced unparseable response",
                    "brief": f"Parse error at step {step_num}",
                }

            # ── Critical safety gate ───────────────────────────────────────────
            if action == "send_auto_reply" and is_critical:
                observation = (
                    "[SAFETY GATE] send_auto_reply blocked: urgency=Critical. "
                    "Forcing escalate_to_human."
                )
                steps.append(AgentStep(
                    step=step_num,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation=observation,
                ))
                return self._finish_escalate(
                    email_row=email_row,
                    steps=steps,
                    reason="Critical urgency — auto-reply blocked by safety gate",
                    brief="Safety gate forced escalation due to Critical urgency.",
                    draft_content=draft_content,
                    dry_run=dry_run,
                    final_action="critical_safety_escalated",
                )

            # ── Dispatch tool ──────────────────────────────────────────────────
            observation = self._dispatch(action, action_input, email_row, dry_run)

            # Track draft content for escalation brief
            if action == "draft_reply":
                draft_content = action_input.get("content", "")

            step = AgentStep(
                step=step_num,
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation,
            )
            steps.append(step)

            # ── Terminal action handling ───────────────────────────────────────
            if action in TERMINAL_ACTIONS:
                if action == "escalate_to_human":
                    return self._finish_escalate(
                        email_row=email_row,
                        steps=steps,
                        reason=action_input.get("reason", ""),
                        brief=action_input.get("brief", ""),
                        draft_content=draft_content,
                        dry_run=dry_run,
                        final_action="escalate_to_human",
                    )
                elif action == "send_auto_reply":
                    return self._finish_auto_reply(
                        email_row=email_row,
                        steps=steps,
                        content=action_input.get("content", ""),
                        dry_run=dry_run,
                    )
                else:  # FINISH
                    summary = action_input.get("summary", "Agent completed reasoning.")
                    return self._finish_complete(
                        email_row=email_row,
                        steps=steps,
                        summary=summary,
                        dry_run=dry_run,
                    )
        else:
            # Loop exhausted — auto-escalate
            summary = " | ".join(
                f"Step {s.step}: {s.action}" for s in steps
            )
            return self._finish_escalate(
                email_row=email_row,
                steps=steps,
                reason=f"Max steps ({MAX_STEPS}) reached without resolution",
                brief=f"Agent hit step limit. Trace: {summary}",
                draft_content=draft_content,
                dry_run=dry_run,
                final_action="max_steps_escalated",
            )

    # ── Prompt construction ────────────────────────────────────────────────────

    def _build_prompt_prefix(self, email_row: Email, thread: Optional[Thread], is_critical: bool) -> str:
        critical_warning = (
            "\n[CRITICAL WARNING: This email has urgency=Critical. "
            "You MUST escalate_to_human. DO NOT use send_auto_reply.]\n"
            if is_critical else ""
        )
        thread_id = thread.thread_id if thread else "unknown"
        return (
            f"{_AGENT_SYSTEM}\n{_TOOL_SPEC}{critical_warning}\n"
            f"=== EMAIL TO PROCESS ===\n"
            f"email_id: {email_row.id}\n"
            f"message_id: {email_row.message_id}\n"
            f"thread_id: {thread_id}\n"
            f"sender: {email_row.sender}\n"
            f"subject: {email_row.subject or ''}\n"
            f"urgency: {email_row.urgency or 'Unknown'}\n"
            f"category: {email_row.category or 'Unknown'}\n"
            f"body:\n{email_row.body or ''}\n"
            f"========================\n"
        )

    def _build_prompt(self, prefix: str, steps: list[AgentStep]) -> str:
        if not steps:
            return prefix + "\nNEXT STEP (respond with JSON only):\n"
        trace = "\n".join(
            f"Step {s.step}:\n"
            f"  Thought: {s.thought}\n"
            f"  Action: {s.action}({json.dumps(s.action_input)})\n"
            f"  Observation: {s.observation}"
            for s in steps
        )
        return prefix + f"\n=== REASONING TRACE SO FAR ===\n{trace}\n\nNEXT STEP (respond with JSON only):\n"

    # ── Tool dispatcher ────────────────────────────────────────────────────────

    def _dispatch(self, action: str, action_input: dict, email_row: Email, dry_run: bool) -> str:
        handlers = {
            "search_knowledge_base":  lambda: self._t_search_kb(action_input),
            "get_thread_history":     lambda: self._t_thread_history(action_input, email_row),
            "get_contact_profile":    lambda: self._t_contact_profile(action_input),
            "check_account_status":   lambda: self._t_account_status(action_input),
            "draft_reply":            lambda: self._t_draft_reply(action_input, dry_run),
            "escalate_to_human":      lambda: self._t_escalate_observe(action_input, dry_run),
            "create_internal_ticket": lambda: self._t_create_ticket(action_input, email_row, dry_run),
            "flag_for_legal":         lambda: self._t_flag_legal(action_input, email_row, dry_run),
            "send_auto_reply":        lambda: self._t_send_auto_reply(action_input, dry_run),
            "scrape_public_sentiment": lambda: self._t_sentiment_stub(action_input),
            "FINISH":                 lambda: "Agent signalled completion.",
        }
        handler = handlers.get(action)
        if handler is None:
            return f"Unknown tool '{action}'. Use one of: {', '.join(handlers.keys())}"
        try:
            return handler()
        except Exception as exc:
            logger.warning("Tool %s raised: %s", action, exc)
            return f"Tool error: {exc}"

    # ── Tools ──────────────────────────────────────────────────────────────────

    def _t_search_kb(self, inp: dict) -> str:
        query = str(inp.get("query", ""))
        results = self._rag.search(query, top_k=3)
        if not results:
            return "No relevant knowledge base chunks found."
        lines = [f"[{r.source_doc}] (score={r.similarity_score:.3f}): {r.chunk_text[:200]}" for r in results]
        return "\n".join(lines)

    def _t_thread_history(self, inp: dict, email_row: Email) -> str:
        thread_id_str = str(inp.get("thread_id", ""))
        thread = self._db.query(Thread).filter(Thread.thread_id == thread_id_str).first()
        if thread is None:
            return f"Thread '{thread_id_str}' not found."
        emails = (
            self._db.query(Email)
            .filter(
                Email.thread_id == thread.id,
                Email.message_id != email_row.message_id,
            )
            .order_by(Email.timestamp.asc())
            .all()
        )
        if not emails:
            return "No prior emails in this thread."
        parts = [
            f"[{e.timestamp}] {e.sender}: {(e.subject or '(no subject)')} — {(e.body or '')[:150]}"
            for e in emails
        ]
        return "\n".join(parts)

    def _t_contact_profile(self, inp: dict) -> str:
        email_addr = str(inp.get("email", ""))
        contact = self._db.query(Contact).filter(Contact.email == email_addr).first()
        if contact is None:
            return f"No contact record for {email_addr}."
        return (
            f"name={contact.name or 'Unknown'}, company={contact.company or 'Unknown'}, "
            f"status={contact.status.value}, account_value={contact.account_value}, "
            f"churn_risk={contact.churn_risk_score}"
        )

    def _t_account_status(self, inp: dict) -> str:
        email_addr = str(inp.get("email", ""))
        contact = self._db.query(Contact).filter(Contact.email == email_addr).first()
        if contact is None:
            return f"No account found for {email_addr}."
        risk = contact.churn_risk_score or 0.0
        value = contact.account_value or 0.0
        risk_label = "HIGH" if risk >= 0.7 else ("MEDIUM" if risk >= 0.4 else "LOW")
        return (
            f"account_status={contact.status.value}, account_value=${value:,.0f}/mo, "
            f"churn_risk={risk:.2f} ({risk_label})"
        )

    def _t_draft_reply(self, inp: dict, dry_run: bool) -> str:
        content = str(inp.get("content", ""))
        if dry_run:
            return f"[DRY-RUN] Draft staged ({len(content)} chars). Not stored."
        return f"Draft staged ({len(content)} chars). Ready for review or send_auto_reply."

    def _t_escalate_observe(self, inp: dict, dry_run: bool) -> str:
        reason = str(inp.get("reason", ""))
        if dry_run:
            return f"[DRY-RUN] Would escalate to human. Reason: {reason}"
        return f"Escalation queued. Reason: {reason}"

    def _t_create_ticket(self, inp: dict, email_row: Email, dry_run: bool) -> str:
        title = str(inp.get("title", ""))
        description = str(inp.get("description", ""))
        if dry_run:
            return f"[DRY-RUN] Ticket '{title}' would be created."
        action = Action(
            email_id=email_row.id,
            action_type=ActionType.TICKET_CREATED,
            proposed_content=f"{title}\n\n{description}",
        )
        self._db.add(action)
        self._db.flush()
        return f"Ticket created (action_id={action.id}): {title}"

    def _t_flag_legal(self, inp: dict, email_row: Email, dry_run: bool) -> str:
        reason = str(inp.get("reason", ""))
        if dry_run:
            return f"[DRY-RUN] Would flag for legal. Reason: {reason}"
        flags = dict(email_row.rule_flags or {})
        flags["legal_flag"] = True
        email_row.rule_flags = flags
        action = Action(
            email_id=email_row.id,
            action_type=ActionType.LEGAL_FLAG,
            proposed_content=reason,
        )
        self._db.add(action)
        self._db.flush()
        return f"Email flagged for legal review (action_id={action.id}). Reason: {reason}"

    def _t_send_auto_reply(self, inp: dict, dry_run: bool) -> str:
        content = str(inp.get("content", ""))
        if dry_run:
            return f"[DRY-RUN] Would send auto-reply ({len(content)} chars)."
        return f"Auto-reply queued ({len(content)} chars)."

    def _t_sentiment_stub(self, inp: dict) -> str:
        company = str(inp.get("company", "Unknown"))
        domain = inp.get("domain")
        try:
            svc = WebIntelligenceService(self._db)
            data = svc.get_sentiment(company, domain)
            return (
                f"Public sentiment for '{company}': {data.get('summary', 'No data')}. "
                f"G2: {data.get('g2', {}).get('rating', 'N/A')}/5 "
                f"({data.get('g2', {}).get('review_count', 0)} reviews). "
                f"Trustpilot: {data.get('trustpilot', {}).get('rating', 'N/A')}/5 "
                f"({data.get('trustpilot', {}).get('review_count', 0)} reviews). "
                f"Themes: {', '.join(data.get('themes', [])[:3]) or 'N/A'}. "
                f"Cached: {data.get('from_cache', False)}."
            )
        except Exception as exc:
            logger.warning("Web intelligence scrape failed for '%s': %s", company, exc)
            return f"Web intelligence unavailable for '{company}' — proceeding without it."

    # ── Terminal finalisers ────────────────────────────────────────────────────

    def _finish_escalate(
        self,
        email_row: Email,
        steps: list[AgentStep],
        reason: str,
        brief: str,
        draft_content: Optional[str],
        dry_run: bool,
        final_action: str = "escalate_to_human",
    ) -> AgentRunResult:
        log = [s.model_dump() for s in steps]
        action_id: Optional[int] = None

        if not dry_run:
            action = Action(
                email_id=email_row.id,
                action_type=ActionType.ESCALATE,
                proposed_content=brief or reason,
                agent_reasoning_log=log,
            )
            self._db.add(action)
            email_row.status = EmailStatus.ESCALATED
            self._db.flush()
            action_id = action.id
            self._db.commit()

        return AgentRunResult(
            email_id=email_row.id,
            message_id=email_row.message_id,
            dry_run=dry_run,
            steps=steps,
            final_action=final_action,
            summary=brief or reason,
            action_id=action_id,
        )

    def _finish_auto_reply(
        self,
        email_row: Email,
        steps: list[AgentStep],
        content: str,
        dry_run: bool,
    ) -> AgentRunResult:
        log = [s.model_dump() for s in steps]
        action_id: Optional[int] = None

        if not dry_run:
            action = Action(
                email_id=email_row.id,
                action_type=ActionType.AUTO_REPLY,
                proposed_content=content,
                is_approved=True,
                approved_by="agent",
                executed_at=datetime.now(tz=timezone.utc),
                agent_reasoning_log=log,
            )
            self._db.add(action)
            email_row.status = EmailStatus.REPLIED
            self._db.flush()
            action_id = action.id
            self._db.commit()

        return AgentRunResult(
            email_id=email_row.id,
            message_id=email_row.message_id,
            dry_run=dry_run,
            steps=steps,
            final_action="send_auto_reply",
            summary=f"Auto-reply sent ({len(content)} chars).",
            action_id=action_id,
        )

    def _finish_complete(
        self,
        email_row: Email,
        steps: list[AgentStep],
        summary: str,
        dry_run: bool,
    ) -> AgentRunResult:
        log = [s.model_dump() for s in steps]
        action_id: Optional[int] = None

        if not dry_run:
            action = Action(
                email_id=email_row.id,
                action_type=ActionType.IGNORED,
                proposed_content=summary,
                agent_reasoning_log=log,
            )
            self._db.add(action)
            self._db.flush()
            action_id = action.id
            self._db.commit()

        return AgentRunResult(
            email_id=email_row.id,
            message_id=email_row.message_id,
            dry_run=dry_run,
            steps=steps,
            final_action="FINISH",
            summary=summary,
            action_id=action_id,
        )
