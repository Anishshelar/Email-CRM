"""
GET /rag/search  — Phase 3.

Exposes the FAISS semantic search layer for direct queries.
Used for debugging retrieval quality and as a building block for the
classification prompt injection at SEARCH TAG: RAG_INJECTION_POINT.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.rag_service import RagService, SearchResult

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Response schema ───────────────────────────────────────────────────────────

class ChunkResult(BaseModel):
    chunk_id: int
    source_doc: str
    chunk_index: int
    chunk_text: str
    similarity_score: float


class RagSearchResponse(BaseModel):
    query: str
    top_k: int
    results: list[ChunkResult]


# ─── Singleton RAG service ─────────────────────────────────────────────────────

# Module-level singleton — index is built once at startup via lifespan handler,
# then shared across all requests. Tests inject a pre-built RagService instance.
_rag_service: Optional[RagService] = None


def get_rag_service() -> RagService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RagService()
    return _rag_service


def set_rag_service(svc: RagService) -> None:
    """Test hook: inject a pre-built RagService instead of the singleton."""
    global _rag_service
    _rag_service = svc


# ─── Endpoint ──────────────────────────────────────────────────────────────────

@router.get(
    "/search",
    response_model=RagSearchResponse,
    summary="Semantic search over the knowledge base",
)
def rag_search(
    q: str = Query(..., min_length=1, description="Natural language query"),
    top_k: int = Query(3, ge=1, le=20, description="Number of results to return"),
) -> RagSearchResponse:
    """
    Return the top_k most semantically relevant knowledge base chunks for query `q`.
    Results are ranked by cosine similarity (0.0–1.0, higher = more relevant).
    The FAISS index must be built before this endpoint is usable — run the seed
    script and then start the server.
    """
    svc = get_rag_service()
    results = svc.search(q, top_k=top_k)

    return RagSearchResponse(
        query=q,
        top_k=top_k,
        results=[
            ChunkResult(
                chunk_id=r.chunk_id,
                source_doc=r.source_doc,
                chunk_index=r.chunk_index,
                chunk_text=r.chunk_text,
                similarity_score=round(r.similarity_score, 4),
            )
            for r in results
        ],
    )
