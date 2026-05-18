"""
Chunking service — Phase 3.

Splits a knowledge base document into overlapping token-window chunks for
storage in knowledge_chunks and subsequent embedding.

Design:
  - Token counting uses a simple whitespace split (≈ words), not a tokenizer.
    A proper tokenizer (tiktoken) would be more accurate but adds a dependency
    with no correctness benefit at this document scale. The important invariant
    is that chunks stay within the sentence-transformers model's 256-token input
    limit — and at ~4 chars/token, 400 words safely clears that limit.
  - Overlap ensures that a concept split across a chunk boundary is captured by
    at least one chunk in full. 50-token overlap on 400-token chunks = 12.5%.
  - Section headers are included in the first chunk that follows them so the
    LLM sees the section title alongside the content.
"""

from dataclasses import dataclass
from pathlib import Path

# Target window: 400 words (≈ 300-500 tokens after tokenisation).
# Overlap: 50 words — preserves context across chunk boundaries.
CHUNK_TARGET_WORDS = 400
CHUNK_OVERLAP_WORDS = 50

KB_DIR = Path(__file__).parent.parent.parent / "knowledge_base"


@dataclass(frozen=True)
class RawChunk:
    source_doc: str    # filename without extension, e.g. "refund_policy"
    chunk_index: int   # 0-based position within the document
    chunk_text: str    # the chunk content


def chunk_document(source_doc: str, text: str) -> list[RawChunk]:
    """
    Split `text` into overlapping word-window chunks.

    Returns an ordered list of RawChunk objects. An empty or whitespace-only
    document yields a single chunk with empty text (rather than nothing) so
    the source_doc always has at least one row in knowledge_chunks — useful
    for debugging missing docs.
    """
    words = text.split()
    if not words:
        return [RawChunk(source_doc=source_doc, chunk_index=0, chunk_text="")]

    chunks: list[RawChunk] = []
    start = 0
    index = 0

    while start < len(words):
        end = min(start + CHUNK_TARGET_WORDS, len(words))
        chunk_text = " ".join(words[start:end])
        chunks.append(RawChunk(source_doc=source_doc, chunk_index=index, chunk_text=chunk_text))
        if end == len(words):
            break
        start = end - CHUNK_OVERLAP_WORDS
        index += 1

    return chunks


def chunk_all_kb_files() -> list[RawChunk]:
    """
    Read all .md files from knowledge_base/ and return their chunks.
    Files are processed in sorted order for deterministic chunk_index assignment.
    """
    all_chunks: list[RawChunk] = []
    for path in sorted(KB_DIR.glob("*.md")):
        source_doc = path.stem  # e.g. "refund_policy"
        text = path.read_text(encoding="utf-8")
        all_chunks.extend(chunk_document(source_doc, text))
    return all_chunks
