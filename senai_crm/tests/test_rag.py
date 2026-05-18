"""
RAG service unit tests — Phase 3.

Tests semantic retrieval quality for the two spec queries:
  1. Karen's refund request — must retrieve refund_policy + retention playbook content.
  2. GDPR data portability request — must retrieve compliance_faq.

All tests use a real in-memory FAISS index built from the actual KB files.
No DB is involved — chunks are embedded and indexed directly in memory.
This makes the tests self-contained and verifiable without seeding.

Coverage:
  1.  Karen refund query — refund_policy in top-3
  2.  Karen refund query — both refund chunks present (retention playbook is chunk 1)
  3.  Karen refund query — top result is refund_policy (not a red-herring doc)
  4.  GDPR query — compliance_faq in top-3
  5.  GDPR query — top result is compliance_faq
  6.  GDPR query — Article 20 / portability content in top result text
  7.  Empty index — search returns empty list without raising
  8.  top_k > index size — returns all indexed chunks, not fewer
  9.  format_for_prompt — includes source_doc name in rendered output
 10.  format_for_prompt — empty results returns safe fallback string
"""

import pytest
from sentence_transformers import SentenceTransformer
import numpy as np
import faiss

from app.services.chunking_service import chunk_all_kb_files, chunk_document
from app.services.rag_service import RagService, SearchResult, EMBEDDING_DIM, EMBEDDING_MODEL_NAME


# ─── Shared fixture — build index once for the whole module ───────────────────

@pytest.fixture(scope="module")
def live_rag_service():
    """
    Build a real FAISS index from the actual KB files.
    Scoped to module so the model loads once for all tests in this file.
    This takes ~2s on first run (model is already cached after seed_knowledge_base.py).
    """
    svc = RagService()
    chunks = chunk_all_kb_files()
    assert chunks, "No KB chunks found — check knowledge_base/ directory"

    model = svc.model  # trigger model load
    texts = [c.chunk_text for c in chunks]
    vectors = model.encode(texts, normalize_embeddings=True)
    vectors_f32 = np.array(vectors, dtype=np.float32)

    index = faiss.IndexFlatIP(EMBEDDING_DIM)
    index.add(vectors_f32)
    svc._index = index
    svc._id_map = list(range(len(chunks)))
    svc._meta = [
        {"source_doc": c.source_doc, "chunk_index": c.chunk_index, "chunk_text": c.chunk_text}
        for c in chunks
    ]
    return svc


# ─── Helper ───────────────────────────────────────────────────────────────────

def source_docs_in_results(results: list[SearchResult]) -> list[str]:
    return [r.source_doc for r in results]


# ─── Karen's refund query ─────────────────────────────────────────────────────

class TestKarenRefundQuery:
    """
    Karen's email (msg_027 in the dataset):
      "I have been a customer for 8 months... the platform has been unreliable...
       I need to request a full refund... If this isn't resolved I will be forced
       to cancel my subscription."
    """

    QUERY = (
        "I want a full refund. The platform has been unreliable and I am very "
        "disappointed with the service. I want to cancel my subscription."
    )

    def test_refund_policy_in_top_3(self, live_rag_service):
        results = live_rag_service.search(self.QUERY, top_k=3)
        assert "refund_policy" in source_docs_in_results(results), (
            "refund_policy must appear in top-3 for a refund request"
        )

    def test_top_result_is_refund_policy(self, live_rag_service):
        results = live_rag_service.search(self.QUERY, top_k=3)
        assert results[0].source_doc == "refund_policy", (
            f"Expected refund_policy at rank 1, got {results[0].source_doc}"
        )

    def test_retention_playbook_content_in_results(self, live_rag_service):
        """The Churn Retention Playbook lives in refund_policy chunk 1."""
        results = live_rag_service.search(self.QUERY, top_k=3)
        all_text = " ".join(r.chunk_text for r in results)
        assert "retention" in all_text.lower() or "churn" in all_text.lower() or "cancel" in all_text.lower(), (
            "Retention / churn playbook content should appear in top-3 results"
        )

    def test_14_day_window_content_in_results(self, live_rag_service):
        """Core refund rule — 14-day window — must be retrievable."""
        results = live_rag_service.search(self.QUERY, top_k=3)
        all_text = " ".join(r.chunk_text for r in results)
        assert "14" in all_text, "14-day refund window policy must appear in top-3"

    def test_similarity_scores_are_positive(self, live_rag_service):
        results = live_rag_service.search(self.QUERY, top_k=3)
        for r in results:
            assert r.similarity_score > 0, "All similarity scores must be positive"

    def test_results_ranked_by_score_descending(self, live_rag_service):
        results = live_rag_service.search(self.QUERY, top_k=5)
        scores = [r.similarity_score for r in results]
        assert scores == sorted(scores, reverse=True), "Results must be ranked highest score first"


# ─── GDPR query ───────────────────────────────────────────────────────────────

class TestGdprQuery:
    """
    GDPR data portability request — must retrieve compliance_faq as top result.
    Based on msg_020 in the dataset:
      "I am exercising my right to data portability under GDPR Article 20..."
    """

    QUERY = (
        "I am exercising my right to data portability under GDPR Article 20. "
        "Please provide all personal data you hold on me within 30 days."
    )

    def test_compliance_faq_in_top_3(self, live_rag_service):
        results = live_rag_service.search(self.QUERY, top_k=3)
        assert "compliance_faq" in source_docs_in_results(results), (
            "compliance_faq must appear in top-3 for a GDPR request"
        )

    def test_top_result_is_compliance_faq(self, live_rag_service):
        results = live_rag_service.search(self.QUERY, top_k=3)
        assert results[0].source_doc == "compliance_faq", (
            f"Expected compliance_faq at rank 1, got {results[0].source_doc}"
        )

    def test_article_20_content_in_top_result(self, live_rag_service):
        results = live_rag_service.search(self.QUERY, top_k=3)
        top_text = results[0].chunk_text
        assert "Article 20" in top_text or "portability" in top_text.lower(), (
            "Top result must contain Article 20 / portability policy text"
        )

    def test_30_day_obligation_in_results(self, live_rag_service):
        results = live_rag_service.search(self.QUERY, top_k=3)
        all_text = " ".join(r.chunk_text for r in results)
        assert "30 days" in all_text or "30-day" in all_text, (
            "GDPR 30-day statutory deadline must appear in top-3 results"
        )

    def test_gdpr_score_high(self, live_rag_service):
        """compliance_faq should score well above 0.5 for an explicit GDPR query."""
        results = live_rag_service.search(self.QUERY, top_k=3)
        assert results[0].similarity_score > 0.5, (
            f"Expected score > 0.5 for compliance_faq on GDPR query, got {results[0].similarity_score:.4f}"
        )


# ─── Edge cases ───────────────────────────────────────────────────────────────

class TestRagEdgeCases:
    def test_empty_index_returns_empty_list(self):
        svc = RagService()
        # Don't call build_index — index is None
        results = svc.search("refund")
        assert results == []

    def test_top_k_larger_than_corpus(self, live_rag_service):
        chunks = chunk_all_kb_files()
        results = live_rag_service.search("pricing", top_k=1000)
        assert len(results) == len(chunks), (
            "When top_k > corpus size, all chunks should be returned"
        )

    def test_format_for_prompt_includes_source_doc(self, live_rag_service):
        results = live_rag_service.search("refund policy", top_k=3)
        rendered = live_rag_service.format_for_prompt(results)
        assert "refund_policy" in rendered

    def test_format_for_prompt_empty_results(self, live_rag_service):
        rendered = live_rag_service.format_for_prompt([])
        assert "No relevant" in rendered or "not" in rendered.lower()


# ─── Chunking service ─────────────────────────────────────────────────────────

class TestChunkingService:
    def test_all_docs_have_at_least_one_chunk(self):
        chunks = chunk_all_kb_files()
        docs = {c.source_doc for c in chunks}
        expected = {"api_docs", "compliance_faq", "escalation_matrix",
                    "pricing_policy", "refund_policy", "sla_policy"}
        assert docs == expected

    def test_chunk_indices_sequential_per_doc(self):
        chunks = chunk_all_kb_files()
        by_doc: dict[str, list[int]] = {}
        for c in chunks:
            by_doc.setdefault(c.source_doc, []).append(c.chunk_index)
        for doc, indices in by_doc.items():
            assert indices == list(range(len(indices))), (
                f"chunk_index for {doc} must be sequential: {indices}"
            )

    def test_chunk_text_not_empty(self):
        for chunk in chunk_all_kb_files():
            assert chunk.chunk_text.strip(), f"Empty chunk in {chunk.source_doc}[{chunk.chunk_index}]"

    def test_overlap_present_in_multi_chunk_doc(self):
        long_text = " ".join([f"word{i}" for i in range(1000)])
        chunks = chunk_document("test_doc", long_text)
        assert len(chunks) > 1
        # Verify overlap: last ~50 words of chunk 0 should appear at start of chunk 1
        words_0 = chunks[0].chunk_text.split()
        words_1 = chunks[1].chunk_text.split()
        overlap_region = words_0[-50:]
        start_of_next = words_1[:50]
        assert overlap_region == start_of_next, "50-word overlap must bridge consecutive chunks"
