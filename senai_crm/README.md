# SenAI CRM — AI-Powered Email Operations System

An end-to-end autonomous email triage and response platform. Emails are ingested via a streaming API, processed by a deterministic rule engine, classified by an LLM with RAG-injected knowledge-base context, and acted on by a ReAct agent that can search knowledge, check accounts, draft replies, flag legal issues, and escalate to humans — all with a full audit trail and a React operations frontend.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Gemini API key (free tier works; get one at https://aistudio.google.com/app/apikey)

### 1. Clone and install

```bash
cd Anish_Shelar_VIT_1221005_SenAI/senai_crm
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set GEMINI_API_KEY=your_key_here
```

### 3. Create the database

```bash
alembic upgrade head
```

### 4. Seed knowledge base and contacts

```bash
# Embed KB documents (downloads ~22 MB sentence-transformers model on first run)
python scripts/seed_knowledge_base.py

# Seed contacts from the email dataset
python scripts/seed_contacts.py
```

### 5. Start the backend

```bash
uvicorn app.main:app --reload --port 8000
```

API: http://localhost:8000 — Interactive docs: http://localhost:8000/docs

### 6. Start the frontend

```bash
cd ../frontend
npm install
npm run dev
```

UI: http://localhost:5173

---

## Environment Variables

Copy `.env.example` to `.env`. All variables have safe defaults for local dev.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./senai_crm.db` | SQLAlchemy DB URL. Swap for `postgresql://` in production. |
| `ENVIRONMENT` | `development` | `development` enables SQL echo logging. |
| `GEMINI_API_KEY` | *(empty)* | **Required** for LLM classification. Without it all emails fall back to `requires_human=True`. |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model name. Flash is fast and cheap for structured JSON output. |
| `SIMULATOR_RATE` | `1.0` | Emails per second for the stream simulator. |

---

## Running the Email Stream Simulator

The simulator replays `email-data-advanced.json` (60 emails) through `POST /api/ingest`. Requires the backend to be running first.

```bash
# Default: 1 email/sec (60-second full replay)
python scripts/stream_simulator.py

# Fast mode for demos
python scripts/stream_simulator.py --rate 5

# Dry-run: print payloads without posting
python scripts/stream_simulator.py --dry-run
```

Prints `NEW` or `DUP` for each email. Re-running is safe — duplicate `message_id` values return `200 {"already_exists": true}` without re-processing.

---

## Running the Test Suite

```bash
# All 151 tests
pytest

# Per-module
pytest tests/test_rule_engine.py -v
pytest tests/test_classification_service.py -v
pytest tests/test_ingest.py -v
pytest tests/test_rag.py -v          # builds real FAISS index (~2s first run)
pytest tests/test_agent.py -v -s     # -s prints the full ReAct trace

# Quiet mode
pytest --tb=short -q
```

Tests use in-memory SQLite and a queue-based `FakeLLMClient` — no API key, no network, no side effects. The RAG tests build a real in-memory FAISS index from the actual KB files.

---

## API Reference

Full OpenAPI spec: `openapi.json`. Key endpoints:

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/ingest` | Ingest one email — rule engine → RAG → LLM |
| `GET` | `/api/emails` | List all ingested emails |
| `GET` | `/api/emails/{id}` | Email detail with actions and reasoning log |
| `GET` | `/api/status/{message_id}` | Processing status by message ID |
| `POST` | `/agent/run/{email_id}` | Run ReAct agent on an email |
| `POST` | `/agent/dry-run/{email_id}` | Agent trace only — no DB writes |
| `GET` | `/rag/search?q=...&top_k=3` | Semantic search over the knowledge base |
| `GET` | `/dashboard/stats` | Aggregate stats + recent emails + at-risk contacts |
| `GET` | `/threads/{contact_email}` | All threads for a contact |
| `POST` | `/respond/{email_id}` | Manual human reply |
| `PATCH` | `/drafts/{id}` | Edit draft content |
| `POST` | `/drafts/{id}/approve` | Approve and send a draft |
| `GET` | `/analytics/sentiment-trend` | Sentiment time-series for a sender |
| `GET` | `/analytics/category-breakdown` | Email count grouped by category |
| `GET` | `/intelligence/reputation?company=...` | Web intelligence (G2 + Trustpilot) |
| `GET` | `/contacts/{email}` | Contact profile |
| `PATCH` | `/contacts/{email}/status` | Update contact status |
| `GET` | `/audit/{entity_type}/{entity_id}` | Audit log for any entity |

---

## Architecture Decisions and Trade-offs

### SQLite vs PostgreSQL

**Choice: SQLite** for development; schema is PostgreSQL-ready.

SQLite eliminates setup friction (no server, no credentials). WAL mode enables concurrent reads. The ORM, Alembic migrations, and `DATABASE_URL` are database-agnostic — switching to PostgreSQL is a one-line `.env` change.

**Trade-off:** SQLite's per-write locking becomes a bottleneck above ~100 concurrent writes/sec. The FAISS index rebuild at startup briefly holds a write lock. Switch to PostgreSQL for any realistic throughput.

### FAISS (in-memory) vs Pinecone / pgvector

**Choice: FAISS IndexFlatIP** in memory, rebuilt from DB on cold start.

At knowledge base size (< 100 chunks), flat exact search is faster than approximate methods and needs no ANN tuning. The DB is source of truth; FAISS holds only float32 vectors. Rebuild takes < 1 second.

**Trade-off:** In-process FAISS doesn't survive worker restarts or scale horizontally. For production, migrate embeddings to pgvector — the SQL cosine-similarity query replaces `faiss.search()` and the rest of `RagService` is unchanged.

### Deterministic-first vs LLM-first routing

**Choice: Rule engine runs first and can hard-stop any email before the LLM is called.**

Safety-critical routing (ransomware → security queue, GDPR Article 20 → legal flag, spam → ignored) is pure Python — no probability, no prompt injection surface. The LLM only enriches emails that pass the deterministic gate. A misconfigured or compromised model can never auto-reply to a ransomware extortion or silently drop a legal notice.

**Trade-off:** The rule engine requires explicit pattern maintenance. Novel threat types not yet in the ruleset won't be caught until a rule is added. The LLM catches open-ended signals; the rule engine catches known patterns.

### sentence-transformers/all-MiniLM-L6-v2

**Choice: Local embedding model, no API key, cached after first download (~22 MB).**

Runs in < 50ms per batch on CPU. 384 dimensions. Cosine similarity via L2-normalised inner product (FAISS IndexFlatIP). The same model seeds and searches, so embeddings are always consistent.

**Trade-off:** `text-embedding-3-small` (OpenAI) scores higher on retrieval benchmarks but adds per-call cost, latency, and an external dependency. For a 6-document knowledge base the quality difference is negligible and the local model is deterministic and free.

### ReAct agent vs pure LLM function calling

**Choice: Custom ReAct loop** with a hard step limit (6) and a deterministic safety gate.

The agent reasons in structured JSON (`{"thought", "action", "action_input"}`). The safety gate is Python code — a `send_auto_reply` on a `Critical` email is blocked unconditionally before the observation is formed. The full reasoning log is persisted to the `actions` table for every run.

**Trade-off:** A true agentic framework (LangGraph, AutoGen) offers better observability tooling and streaming but adds a heavyweight dependency. The custom loop is 200 lines of Python and is fully testable with `FakeAgentLLM`.

---

## Known Limitations

- **Web scraping**: G2 and Trustpilot block server-side scrapers. `WebIntelligenceService` attempts a live scrape, checks `robots.txt`, and falls back to deterministic mock data when blocked. In production, use official partner APIs.
- **No WebSocket**: The frontend polls every 10 seconds. Replace the `setInterval` with Server-Sent Events or WebSocket for real-time updates.
- **Single-agent**: One agent instance per email, run sequentially. Multi-agent parallelism (one agent per thread, coordinator for routing) is a natural extension.
- **No authentication**: The API has no auth layer. Add FastAPI's `HTTPBearer` middleware before exposing to any network.
- **FAISS not persisted to disk**: The index is rebuilt from the DB on every restart. For large corpora (> 100K chunks), serialise with `faiss.write_index` and load on startup.
