# Importing all models here ensures Alembic's autogenerate sees every table
# when it inspects Base.metadata. Order matters for FK resolution.
from app.models.contact import Contact
from app.models.thread import Thread
from app.models.email import Email
from app.models.action import Action
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.web_intelligence import WebIntelligenceCache
from app.models.audit_log import AuditLog
from app.models.enums import ContactStatus, ThreadStatus, EmailStatus, ActionType

__all__ = [
    "Contact",
    "Thread",
    "Email",
    "Action",
    "KnowledgeChunk",
    "WebIntelligenceCache",
    "AuditLog",
    "ContactStatus",
    "ThreadStatus",
    "EmailStatus",
    "ActionType",
]
