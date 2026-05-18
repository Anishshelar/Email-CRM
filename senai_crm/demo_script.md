# SenAI CRM — Demo Recording Script

**Target duration:** 5–10 minutes  
**Resolution:** 1920×1080, browser at 100% zoom  
**Setup required before recording** (see Verified Assertions below first)

---

## Pre-Recording Setup Checklist

1. **Backend running:**
   ```bash
   cd senai_crm
   uvicorn app.main:app --reload --port 8000
   ```

2. **Frontend running:**
   ```bash
   cd frontend
   npm run dev
   ```

3. **DB has demo data** (run once, skip if already done):
   ```bash
   # From project root
   python scripts/stream_simulator.py --rate 10
   ```
   Wait for "Stream complete." (about 6 seconds at rate=10).

4. **Browser tabs open before recording:**
   - Tab 1: `http://localhost:5173` (Inbox)
   - Tab 2: `http://localhost:8000/docs` (Swagger — for RAG search demo)

5. **Terminal visible** (split screen or switch) for the stream simulator.

---

## Verified Assertions (Pre-Flight Check)

Run these before recording to confirm the system state:

```bash
python -c "
import httpx, json

# 1. msg_038 (ransomware) was never auto-replied
r = httpx.get('http://localhost:8000/api/status/msg_038').json()
assert r['status'] == 'Escalated', f'Expected Escalated, got {r[\"status\"]}'
detail = httpx.get(f'http://localhost:8000/api/emails/{r[\"email_id\"]}').json()
flags = detail['rule_flags']
assert flags['skip_llm_pipeline'] == True, 'msg_038 should have skip_llm_pipeline=True'
assert flags['security_flag'] == True, 'msg_038 should have security_flag=True'
print('OK msg_038: Escalated, never auto-replied, security_flag=True')

# 2. msg_052 has legal_flag=True
r52 = httpx.get('http://localhost:8000/api/status/msg_052').json()
detail52 = httpx.get(f'http://localhost:8000/api/emails/{r52[\"email_id\"]}').json()
flags52 = detail52['rule_flags']
assert flags52['legal_flag'] == True, 'msg_052 should have legal_flag=True'
assert flags52['gdpr_flag'] == True, 'msg_052 should have gdpr_flag=True'
print('OK msg_052: legal_flag=True, gdpr_flag=True')

# 3. Duplicate returns already_exists=true
dup = httpx.post('http://localhost:8000/api/ingest', json={
    'message_id': 'msg_038',
    'sender': 'hacker@anon-collective.net',
    'subject': 'test',
    'body': 'test',
    'timestamp': '2023-10-01T00:00:00Z',
    'thread_id': 'thread_test'
}).json()
assert dup['already_exists'] == True, 'Duplicate should return already_exists=True'
print('OK duplicate: already_exists=True returned for msg_038')

print('All pre-flight checks passed.')
"
```

The bob_outage 6-step trace is verified by the test suite:
```bash
pytest tests/test_agent.py -v -s 2>&1 | grep -E "(PASSED|Step|Final)"
```

---

## Recording Sequence

### Scene 1: Stream Simulator — Live Inbox Fill (1 min)

**Goal:** Show emails flowing into the inbox in real time with automatic classification badges.

1. Open browser to `http://localhost:5173` (Inbox view — currently empty or showing prior data).
2. Switch to terminal. Run:
   ```bash
   python scripts/stream_simulator.py --rate 3
   ```
3. Switch back to browser. **Every ~3 seconds, a new row appears.** Point out:
   - Sentiment badges turning red for angry emails (karen, bob outage, ransomware)
   - Critical/High urgency badges on the outage and legal emails
   - `msg_038` appears with **Escalated** status and no auto-reply column
   - The **Needs Human** tab counter climbing
4. Click the **Needs Human** tab to filter to only emails requiring review.

**Talking point:** *"The rule engine runs synchronously on every ingest, hard-stopping security threats before they ever reach the LLM. msg_038 is a ransomware extortion — it's immediately escalated with no model involvement."*

---

### Scene 2: Bob Outage Thread — Agent ReAct Trace (2–3 min)

**Goal:** Show the full 6-step ReAct reasoning trace in the thread workspace.

1. In the Inbox, click on **msg_060** ("Escalation: SLA Breach + Legal Review" from `bob.jones@enterprise.net`).
2. The **Thread Workspace** opens. Point out:
   - Right panel: Contact card showing `$15,000/mo`, churn risk `87%` (red bar)
   - Left panel: thread timeline showing all 3 Bob emails (P0 outage → 47-min SLA breach → legal escalation)
   - The `Critical` urgency badge and `Legal` category
3. Click **Run Agent** button.
4. Wait 5–10 seconds for the agent to complete (Gemini API call).
5. The **Agent Reasoning Trace** section appears. Expand it. Walk through each step:
   - **Step 1** — `get_thread_history`: retrieved prior P0 outage and SLA demand emails
   - **Step 2** — `search_knowledge_base`: queried SLA breach / credit obligation
   - **Step 3** — `check_account_status`: confirmed `$15K/mo`, `churn_risk=0.87 HIGH`
   - **Step 4** — `flag_for_legal`: set `legal_flag=True`, created Legal-Flag action
   - **Step 5** — `draft_reply`: staged a holding reply
   - **Step 6** — `escalate_to_human`: terminal action with full context brief

**Talking point:** *"The agent can't auto-reply here — urgency=Critical triggers the Python safety gate before the observation is even formed. The full reasoning log is persisted to the database so every decision is auditable."*

> **If Gemini key is not configured:** The agent will immediately escalate with `requires_human=True`. To demonstrate the full trace, run the test suite which uses `FakeAgentLLM`:
> ```bash
> pytest tests/test_agent.py::TestBobOutageTrace -v -s
> ```

---

### Scene 3: RAG Search — Knowledge Base Retrieval (45 sec)

**Goal:** Show semantic search over the knowledge base with similarity scores.

1. Switch to browser Tab 2 (Swagger at `http://localhost:8000/docs`).
2. Open **GET /rag/search**.
3. Enter query: `SLA breach credit outage root cause analysis obligation`
4. Click **Execute**.
5. Show the response — three chunks with `similarity_score` values, `source_doc` labels, and truncated `chunk_text`.
6. Point out that `sla_policy` appears at rank 1 with score > 0.5.

**Alternative (Thread Workspace):** Back in Bob's thread, scroll down to **Knowledge Base Matches**, click **Expand**. The same search runs live against the current email's subject+body and shows the results inline.

**Talking point:** *"The RAG service uses FAISS flat exact search on 384-dimensional embeddings from `all-MiniLM-L6-v2`. The same index powers both the classification prompt injection and the agent's `search_knowledge_base` tool."*

---

### Scene 4: Karen's Thread — Consecutive-Negative Escalation Alert (1 min)

**Goal:** Show the sentiment trend escalation alert and the web intelligence trigger.

1. Back in the Inbox, find any email from `karen.w@retail-co.com` (search or scroll).
2. Note the **red sentiment badge** — three consecutive negative emails in her thread.
3. Switch to the **Analytics** tab.
4. In the **Sentiment Trend** section, enter sender: `karen.w@retail-co.com`, click **Load**.
5. Show the chart — three data points, all below 0, with the 3-pt moving average line.
6. The red **escalation alert** banner appears: *"3 consecutive negative emails"*.
7. Back in Karen's thread workspace, notice the body of `msg_033` mentions **"G2, Capterra, and Trustpilot"** — this triggers the web intelligence tool.
8. If the agent is run on msg_033, `scrape_public_sentiment` is called for the company. Expand the agent trace to show it.

**Talking point:** *"The rule engine already flags `msg_033` as `skip_llm_pipeline=True` because it's a hard-stop escalation. Web intelligence is only called by the agent on emails that pass the gate. For a Complaint+Critical email mentioning G2 or Trustpilot, the agent automatically checks the company's public rating."*

---

### Scene 5: Analytics Dashboard (1 min)

**Goal:** Show the three analytics panels.

1. Click the **Analytics** nav link.
2. **Category Breakdown** (bar chart) — show the distribution across Billing, Technical, Complaint, Legal, Inquiry, etc.
3. **At-Risk Accounts** (table) — scroll to `bob.jones@enterprise.net` at the top (`87%` churn risk, `$15K/mo`). Point out the red risk bar.
4. **Sentiment Trend** — load `karen.w@retail-co.com` again if not already loaded. Show the escalation alert panel above the chart.

**Talking point:** *"The analytics layer is pure SQL aggregation — no LLM, no approximation. The at-risk list is contacts with `churn_risk_score ≥ 0.7`. The sentiment trend uses a causal 3-point moving average so the most recent signal is always weighted."*

---

## Closing Shot (15 sec)

Return to `http://localhost:8000/docs` and scroll through the 19 endpoints — show the full API surface. Briefly navigate to `openapi.json` in the project directory.

**Final talking point:** *"Everything you've seen — rule engine, RAG, LLM classification, ReAct agent, web intelligence, REST API, and React frontend — is in this one repository. 151 tests, deterministic safety gates, and a full audit trail for every action."*

---

## Appendix: Message Reference

| Message ID | Sender | Subject | Key Demo Property |
|---|---|---|---|
| `msg_002` | `bob.jones@enterprise.net` | URGENT: Production System Down | P0 outage, start of bob thread |
| `msg_009` | `bob.jones@enterprise.net` | Re: URGENT: Production System Down | 47-min SLA breach demand |
| `msg_060` | `bob.jones@enterprise.net` | Escalation: SLA Breach + Legal Review | **Agent demo** — 6-step ReAct trace |
| `msg_006` | `karen.w@retail-co.com` | Refund Request - Order #88271 | Refund + cancel, negative sentiment |
| `msg_018` | `karen.w@retail-co.com` | Re: Refund Request - STILL NO REPLY | Second negative — escalating frustration |
| `msg_033` | `karen.w@retail-co.com` | Final Warning Before Public Review | Third negative — G2/Trustpilot mention, web intel trigger |
| `msg_038` | `hacker@anon-collective.net` | We have your data - Pay Now | **Ransomware** — hard-stop, never auto-replied |
| `msg_052` | `marcus.del@fintech-startup.co` | Data Export: GDPR Right to Portability Request | **GDPR** — `legal_flag=True`, `gdpr_flag=True` |
| `msg_020` | `legal@competitor-corp.com` | Cease and Desist Notice | Trademark dispute, legal hard-stop |
