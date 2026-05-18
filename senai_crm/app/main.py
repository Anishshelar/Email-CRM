import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ingest, analytics, rag, agent
from app.api import dashboard, threads_api, respond, drafts, intelligence, audit_api, contacts_api
from app.api.rag import get_rag_service
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the FAISS index from knowledge_chunks at startup.
    # If the table is empty, build_index logs a warning and search returns [].
    db = SessionLocal()
    try:
        svc = get_rag_service()
        svc.build_index(db)
    except Exception as exc:
        logger.warning("RAG index build failed at startup (non-fatal): %s", exc)
    finally:
        db.close()
    yield
    # Nothing to tear down.


app = FastAPI(
    title="SenAI CRM",
    description="AI-powered email operations and triage system",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "phase": 4}


# Core
app.include_router(ingest.router, prefix="/api", tags=["ingest"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(rag.router, prefix="/rag", tags=["rag"])
app.include_router(agent.router, prefix="/agent", tags=["agent"])

# Phase 5
app.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
app.include_router(threads_api.router, prefix="/threads", tags=["threads"])
app.include_router(respond.router, prefix="/respond", tags=["respond"])
app.include_router(drafts.router, prefix="/drafts", tags=["drafts"])
app.include_router(intelligence.router, prefix="/intelligence", tags=["intelligence"])
app.include_router(audit_api.router, prefix="/audit", tags=["audit"])
app.include_router(contacts_api.router, prefix="/contacts", tags=["contacts"])
