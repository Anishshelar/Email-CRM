"""
Pydantic schemas for the AgentOrchestrator API — Phase 4.
"""
from typing import Optional
from pydantic import BaseModel


class AgentStep(BaseModel):
    step: int
    thought: str
    action: str
    action_input: dict
    observation: str


class AgentRunResult(BaseModel):
    email_id: int
    message_id: str
    dry_run: bool
    steps: list[AgentStep]
    final_action: str
    summary: str
    action_id: Optional[int] = None
