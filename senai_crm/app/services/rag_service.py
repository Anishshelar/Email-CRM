"""
RAG (Retrieval-Augmented Generation) service — Phase 3.

Responsibilities:
  1. Load all knowledge_chunks rows from DB on cold start.
  2. Embed each chunk using sentence-transformers/all-MiniLM-L6-v2 (local, no API key).
  3. Build a FAISS flat L2 index in memory (exact search; corpus is small enough).
  4. search_knowledge_base(query, top_k) → cosine-similarity-ranked chunks with scores.

Architecture decisions:
  - DB is the source of truth for chunk text. FAISS holds only the embedding vectors
    plus an integer mapping back to knowledge_chunks.id. On every cold start, FAISS
    is rebuilt from DB — no serialised index file to keep in sync.
  - Cosine similarity via normalised L2: we L2-normalise all vectors before indexing,
    so inner product (IndexFlatIP) equals cosine similarity. This avoids a separate
    FAISS index type and keeps the math transparent.
  - The model is loaded once (lazy singleton) and shared across all requests.
    sentence-transformers loads the model from ~/.cache/huggingface on first run;
    subsequent starts use the cached weights (no download needed after first run).
  - Thread safety: FAISS reads are thread-safe; the index is rebuilt only at startup,
    not during serving. No lock is needed for search.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

from app.models.knowledge_chunk import KnowledgeChunk

logger = logging.getLogger(__name__)

# all-MiniLM-L6-v2: 384-dim embeddings, 256-token limit, ~22MB on disk.
# Good accuracy/speed balance; standard choice for semantic search on short docs.
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


@dataclass
class SearchResult:
    chunk_id: int
    source_doc: str
    chunk_index: int
    chunk_text: str
    similarity_score: float   # cosine similarity, 0.0–1.0 (higher = more relevant)


class RagService:
    """
    Manages the embedding model, FAISS index, and chunk search.

    Usage:
        svc = RagService()
        svc.build_index(db)          # call once at startup
        results = svc.search("refund policy", top_k=3)
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME) -> None:
        self._model: Optional[SentenceTransformer] = None
        self._model_name = model_name
        self._index: Optional[faiss.IndexFlatIP] = None
        # Ordered list of chunk IDs in the same order as rows in the FAISS index.
        # index position i → _id_map[i] is the knowledge_chunks.id value.
        self._id_map: list[int] = []
        # Parallel metadata list for fast result construction without a DB round-trip.
        self._meta: list[dict] = []

    # ── Model loading ──────────────────────────────────────────────────────────

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading embedding model: %s", self._model_name)
            self._model = SentenceTransformer(self._model_name)
            logger.info("Embedding model loaded (dim=%d)", EMBEDDING_DIM)
        return self._model

    # ── Index construction ────────────────────────────────────────────────────

    def build_index(self, db: Session) -> None:
        """
        Load all knowledge_chunks from DB, embed them, and build the FAISS index.
        Called once at application startup (or after a re-seed).
        """
        rows = db.query(KnowledgeChunk).order_by(KnowledgeChunk.id).all()
        if not rows:
            logger.warning("knowledge_chunks table is empty — RAG search will return nothing. Run the seed script.")
            self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
            return

        texts = [r.chunk_text for r in rows]
        logger.info("Embedding %d chunks with %s …", len(texts), self._model_name)
        vectors = self.model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        vectors = np.array(vectors, dtype=np.float32)

        # IndexFlatIP + pre-normalised vectors = cosine similarity search.
        index = faiss.IndexFlatIP(EMBEDDING_DIM)
        index.add(vectors)

        self._index = index
        self._id_map = [r.id for r in rows]
        self._meta = [
            {"source_doc": r.source_doc, "chunk_index": r.chunk_index, "chunk_text": r.chunk_text}
            for r in rows
        ]
        logger.info("FAISS index built: %d vectors indexed", index.ntotal)

    # ── Search ─────────────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 3) -> list[SearchResult]:
        """
        Return the top_k most semantically similar chunks for `query`.

        Returns an empty list if the index hasn't been built or is empty.
        Never raises — callers fall back to the RAG placeholder if this returns [].
        """
        if self._index is None or self._index.ntotal == 0:
            logger.warning("RAG search called but index is empty — returning []")
            return []

        query_vec = self.model.encode([query], normalize_embeddings=True)
        query_vec = np.array(query_vec, dtype=np.float32)

        k = min(top_k, self._index.ntotal)
        scores, indices = self._index.search(query_vec, k)

        results: list[SearchResult] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue  # FAISS returns -1 for padding when ntotal < k
            meta = self._meta[idx]
            results.append(
                SearchResult(
                    chunk_id=self._id_map[idx],
                    source_doc=meta["source_doc"],
                    chunk_index=meta["chunk_index"],
                    chunk_text=meta["chunk_text"],
                    similarity_score=float(score),
                )
            )
        return results

    def format_for_prompt(self, results: list[SearchResult]) -> str:
        """
        Render search results as the RAG context block injected into the LLM prompt.
        Replaces _RAG_PLACEHOLDER at SEARCH TAG: RAG_INJECTION_POINT in classification_service.
        """
        if not results:
            return "[RAG] No relevant knowledge base chunks found."

        lines = ["[RAG — Top knowledge base chunks retrieved for this email]\n"]
        for i, r in enumerate(results, 1):
            lines.append(
                f"[{i}] Source: {r.source_doc}  |  Similarity: {r.similarity_score:.3f}\n"
                f"{r.chunk_text}\n"
            )
        return "\n".join(lines)
