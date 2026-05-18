from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(Integer, primary_key=True, index=True)
    source_doc = Column(String, nullable=False)  # e.g. "pricing_policy.md"
    chunk_index = Column(Integer, nullable=False)  # position within source doc

    chunk_text = Column(Text, nullable=False)

    # Phase 1 placeholder: stored as a JSON-encoded float list (e.g. [0.12, -0.34, ...]).
    # Trade-off: no native vector similarity search in SQLite. In Phase 3, the FAISS
    # index is built at startup by reading these float arrays into memory. The DB is
    # the durable store; FAISS is the ANN search layer. This avoids a vector DB
    # dependency for Phase 1 while keeping the migration path clean.
    embedding = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("source_doc", "chunk_index", name="uq_chunk_doc_index"),
    )
