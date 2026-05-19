# SenAI CRM — AI-Powered Email Operations System

An autonomous email triage system that classifies incoming customer emails, detects urgency and sentiment, flags legal/security issues, and drafts replies — all visible in a live React dashboard.

---

## What it does

- **Classifies emails** into categories: Complaint, Inquiry, Feature Request, Billing, Spam, etc.
- **Scores sentiment** from -1.0 (very negative) to +1.0 (very positive)
- **Flags risky emails** — ransomware, GDPR requests, legal threats are escalated immediately
- **Tracks churn risk** — contacts with repeated negative emails are highlighted
- **Live inbox** — emails stream in one-by-one and appear in real time on the dashboard

---

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python, FastAPI, SQLite |
| Frontend | React + Vite |
| LLM | Groq (llama-3.1-8b-instant) — free, fast |
| Embeddings | sentence-transformers (local, no API key needed) |
| Vector search | FAISS (in-memory) |

---

## Setup

### Requirements

- Python 3.11+
- Node.js 18+
- A free Groq API key — get one at https://console.groq.com

---

### Step 1 — Clone the repo

```bash
git clone https://github.com/Anishshelar/Email-CRM.git
cd Email-CRM
```

---

### Step 2 — Install Python dependencies

```bash
cd senai_crm
pip install -r requirements.txt
```

---

### Step 3 — Set up environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your Groq API key:

```
GROQ_API_KEY=your_key_here
LLM_PROVIDER=groq
```

---

### Step 4 — Create the database

```bash
alembic upgrade head
```

---

### Step 5 — Seed the knowledge base

```bash
python scripts/seed_knowledge_base.py
python scripts/seed_contacts.py
```

> First run downloads a ~22 MB embedding model. This only happens once.

---

### Step 6 — Start the backend

```bash
python -m uvicorn app.main:app --port 8000
```

Backend runs at http://localhost:8000
Interactive API docs at http://localhost:8000/docs

---

### Step 7 — Start the frontend

Open a new terminal:

```bash
cd ../frontend
npm install
npm run dev
```

Frontend runs at http://localhost:5173

---

## Running the Demo

Open a third terminal. This clears the database so the inbox starts empty, then streams all 60 demo emails one-by-one:

```bash
cd senai_crm

# Wipe existing data (inbox starts empty)
python scripts/demo_reset.py

# Stream emails live — one every 2 seconds
python scripts/stream_simulator.py --rate 0.5
```

Watch http://localhost:5173 — emails appear in real time with category badges, sentiment scores, and urgency labels as the AI classifies them.

---

## Pre-flight Check

Before a demo, run this to verify everything is working:

```bash
cd senai_crm
python preflight.py
```

Expected output:
```
OK msg_038: ESCALATED, skip_llm_pipeline=True, security_flag=True
OK msg_052: legal_flag=True, gdpr_flag=True
OK duplicate: already_exists=True for msg_038
All pre-flight checks passed.
```

---

## Project Structure

```
Email-CRM/
├── senai_crm/                  # Python backend
│   ├── app/
│   │   ├── api/                # FastAPI endpoints
│   │   ├── models/             # SQLAlchemy models
│   │   ├── services/           # LLM, RAG, rule engine
│   │   └── main.py
│   ├── scripts/
│   │   ├── stream_simulator.py # Replays 60 demo emails
│   │   └── demo_reset.py       # Clears DB before a demo
│   ├── preflight.py            # Smoke test
│   ├── .env.example            # Copy to .env and fill in keys
│   └── requirements.txt
├── frontend/                   # React + Vite dashboard
│   └── src/
│       └── views/
│           ├── Inbox.jsx
│           ├── Analytics.jsx
│           └── ThreadWorkspace.jsx
└── email-data-advanced.json    # 60 demo emails
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Your Groq API key (required) |
| `GROQ_MODEL` | Model to use — default `llama-3.1-8b-instant` |
| `LLM_PROVIDER` | Set to `groq` |
| `DATABASE_URL` | Default `sqlite:///./senai_crm.db` |
| `SIMULATOR_RATE` | Emails per second for the simulator — default `1.0` |
