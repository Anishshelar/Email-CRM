"""
Pydantic schemas for the email ingest endpoint.
Stub — full validation logic is wired up in the next commit when POST /api/ingest is built.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator


class EmailIngestRequest(BaseModel):
    message_id: str
    sender: str
    subject: Optional[str] = None
    body: Optional[str] = None
    timestamp: datetime
    thread_id: str

    @field_validator("message_id", "sender", "thread_id")
    @classmethod
    def must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field must not be blank")
        return v.strip()


class EmailIngestResponse(BaseModel):
    message_id: str
    already_exists: bool      # True on duplicate — idempotent ingest
    email_id: int
    thread_id: str
    priority_score: int
    rule_flags: dict
    status: str
    rag_chunks_used: list[str] = []
