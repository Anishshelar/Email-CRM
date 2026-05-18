"""
POST /agent/run/{email_id}      — run the agent on an email (full execution)
POST /agent/dry-run/{email_id}  — produce trace without executing write tools
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.rag import get_rag_service
from app.database import get_db
from app.schemas.agent import AgentRunResult
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.llm_client import LLMClientProtocol, get_default_client

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Dependency ─────────────────────────────────────────────────────────────────

_llm_client: LLMClientProtocol | None = None


class _NoopLLMClient:
    def generate(self, prompt: str) -> str:
        raise RuntimeError("LLM client not configured (GEMINI_API_KEY missing)")


def _get_llm_client() -> LLMClientProtocol:
    global _llm_client
    if _llm_client is None:
        try:
            _llm_client = get_default_client()
        except ValueError as exc:
            logger.warning("LLM client unavailable (%s); agent will error on any run", exc)
            _llm_client = _NoopLLMClient()
    return _llm_client


def set_agent_llm_client(client: LLMClientProtocol) -> None:
    """Test hook: inject a scripted fake LLM."""
    global _llm_client
    _llm_client = client


def _get_agent_orchestrator(
    db: Session = Depends(get_db),
) -> AgentOrchestrator:
    llm = _get_llm_client()
    rag = get_rag_service()
    return AgentOrchestrator(llm_client=llm, rag_service=rag, db=db)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/run/{email_id}",
    response_model=AgentRunResult,
    summary="Run the agent on an email (full execution — writes actions to DB)",
)
def run_agent(
    email_id: int,
    orchestrator: AgentOrchestrator = Depends(_get_agent_orchestrator),
) -> AgentRunResult:
    try:
        return orchestrator.run(email_id, dry_run=False)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/dry-run/{email_id}",
    response_model=AgentRunResult,
    summary="Dry-run the agent — returns full reasoning trace, no DB writes",
)
def dry_run_agent(
    email_id: int,
    orchestrator: AgentOrchestrator = Depends(_get_agent_orchestrator),
) -> AgentRunResult:
    try:
        return orchestrator.run(email_id, dry_run=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
