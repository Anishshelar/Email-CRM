"""
Seed script — Phase 3.

Reads all .md files from knowledge_base/, chunks them, embeds each chunk
using sentence-transformers/all-MiniLM-L6-v2, and upserts rows into the
knowledge_chunks table.

Usage:
    python scripts/seed_knowledge_base.py [--force]

Flags:
    --force  Truncate the table before seeding (re-embeds everything from scratch).
             Default: upsert (skip if source_doc + chunk_index already exists).

This script is idempotent by default: re-running without --force adds only
new chunks (e.g. if a KB file was updated after the last seed).

Model download:
    On first run, sentence-transformers downloads all-MiniLM-L6-v2 (~22MB)
    into ~/.cache/huggingface. Subsequent runs use the cached weights.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # add senai_crm/ to path

import numpy as np
from sentence_transformers import SentenceTransformer

import app.models  # register all models on Base.metadata before creating DB
from app.database import SessionLocal
from app.models.knowledge_chunk import KnowledgeChunk
from app.services.chunking_service import chunk_all_kb_files

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def main(force: bool = False) -> None:
    db = SessionLocal()
    try:
        if force:
            deleted = db.query(KnowledgeChunk).delete()
            db.commit()
            logger.info("Truncated knowledge_chunks: deleted %d rows", deleted)

        logger.info("Chunking knowledge base files …")
        chunks = chunk_all_kb_files()
        logger.info("Total chunks: %d across %d files",
                    len(chunks),
                    len({c.source_doc for c in chunks}))

        logger.info("Loading embedding model: %s", EMBEDDING_MODEL_NAME)
        model = SentenceTransformer(EMBEDDING_MODEL_NAME)

        texts = [c.chunk_text for c in chunks]
        logger.info("Embedding %d chunks …", len(texts))
        vectors = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

        inserted = 0
        skipped = 0
        for chunk, vector in zip(chunks, vectors):
            existing = (
                db.query(KnowledgeChunk)
                .filter(
                    KnowledgeChunk.source_doc == chunk.source_doc,
                    KnowledgeChunk.chunk_index == chunk.chunk_index,
                )
                .first()
            )
            if existing is not None:
                skipped += 1
                continue

            row = KnowledgeChunk(
                source_doc=chunk.source_doc,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                embedding=vector.tolist(),
            )
            db.add(row)
            inserted += 1

        db.commit()
        logger.info("Done. Inserted: %d  Skipped (already exists): %d", inserted, skipped)

        # Summary table
        counts = (
            db.query(KnowledgeChunk.source_doc, db.query(KnowledgeChunk).filter(
                KnowledgeChunk.source_doc == KnowledgeChunk.source_doc
            ).count)
        )
        from sqlalchemy import func
        rows = (
            db.query(KnowledgeChunk.source_doc, func.count(KnowledgeChunk.id))
            .group_by(KnowledgeChunk.source_doc)
            .order_by(KnowledgeChunk.source_doc)
            .all()
        )
        print("\n── Chunk counts by document ─────────────────")
        for source_doc, count in rows:
            print(f"  {source_doc:<30} {count} chunks")
        print(f"  {'TOTAL':<30} {sum(c for _, c in rows)} chunks")
        print()

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed knowledge base chunks and embeddings")
    parser.add_argument("--force", action="store_true", help="Truncate table before seeding")
    args = parser.parse_args()
    main(force=args.force)
