# Incident Response Agent

An AI incident-response agent that **remembers previous incidents** (root causes, fixes, failed fixes and outcomes) using **[Hindsight](https://hindsight.vectorize.io/)**, and uses that memory when it analyzes new, similar incidents.

Built for HackwithHyderabad 3.0.

## Problem

When production breaks, the knowledge needed to fix it quickly usually already exists. Someone fixed something similar last month. That knowledge is scattered across Slack threads, postmortems and people's heads, so on-call engineers start from scratch each time. A generic LLM makes this worse: it gives plausible but generic advice and has no idea what *your* systems did before.

## Solution

The agent runs a memory loop:

```text
Recall past knowledge → use it with the current incident → generate answer → learn from the resolution
```

1. **Recall:** when a new incident comes in, the backend queries Hindsight for previous incidents with the same service, similar symptoms or error signatures, and their root causes, solutions, failed approaches and outcomes.
2. **Reason:** Groq receives the current incident *and* the recalled memory. It is instructed to treat history as evidence, not as the answer. It compares the incidents and states the similarities and the differences.
3. **Learn automatically:** after every analysis, a Groq extraction step decides what is worth remembering. It keeps root causes, fixes, diagnostic findings, incident patterns, service knowledge, configuration lessons and standing team rules. The backend then **retains** only those short knowledge items in Hindsight, with no click needed. It does not store raw incident text or logs, temporary instructions ("be brief"), duplicates of what is already in memory, or secrets and personal data (these are redacted). Root causes and fixes from an analysis are stored as *unconfirmed*.
4. **Personalize:** the agent also keeps a long-term **preference profile** for each user in Hindsight. It is recalled before every response and applied even when no instruction is given. It learns automatically from the *Additional Instructions* field:
   * An explicit lasting preference ("End every summary with OK", "always respond in Spanish") is stored immediately.
   * A change or cancellation ("Stop ending summaries with OK") updates or removes the stored preference.
   * A one-off request ("be brief this time") is **not** stored. It only becomes a learned preference if the user asks for it in 3 separate reports.

   The profile is a single Hindsight document (`user-preference-profile`), rewritten with `update_mode="replace"`, so cancelled preferences are removed from memory rather than piling up.
5. **Confirm (optional):** when an engineer saves the actual resolution, it is retained as *confirmed* knowledge, and confirmed details take precedence over the earlier suspicions at recall time.

Hindsight is the only memory layer. SQLite only holds login sessions and the incident list shown in the history table; the agent never reads its "memory" from SQLite.

## Architecture

```text
User (React + Vite + Tailwind)
 ↓  POST /api/incidents/analyze
FastAPI
 ↓
Hindsight Recall        (hindsight-client → arecall, tag-filtered to incident memories)
 ↓
Historical Memory       (grouped per previous incident, filtered for relevance)
 ↓
Preferences             (documents.get_document "user-preference-profile" in the user's bank)
 ↓
Groq                    (current incident + incident memory + user preferences + current instruction → JSON)
 ↓
Memory extraction       (Groq decides what is worth remembering; secrets redacted; duplicates skipped)
 ↓
Hindsight Retain        (aretain, document_id = <incident id>:analysis, marked unconfirmed)
 ↓
AI Analysis             (shown with the recalled memories)
 ↓  optional: POST /api/incidents/{id}/resolve
Hindsight Retain        (aretain, document_id = <incident id>, confirmed resolution)
```

```text
backend/
  app/
    main.py                 FastAPI app, CORS, /api/health
    config.py               settings from .env
    db.py                   SQLite (sessions + incident list only)
    schemas.py              Pydantic models (input, recall, analysis)
    api/auth.py             POST /api/auth/login, /logout
    api/incidents.py        analyze / resolve / list / get / memories
    agent/incident_agent.py recall → prompt → Groq → validate → auto-remember
    agent/memory_extractor.py decides what is worth remembering, redacts secrets
    agent/preference_learner.py learns/updates/cancels long-term user preferences
    hindsight/preferences.py  per-user preference profile stored in Hindsight
    hindsight/client.py     Hindsight recall + retain (official SDK)
    groq/client.py          Groq chat completions (JSON mode, error handling)
frontend/
  src/pages/Login.tsx, Dashboard.tsx
  src/components/           IncidentForm, MemoryPanel, AnalysisPanel, ResolutionPanel, HistoryTable
  src/services/api.ts
```

### API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Create an account (and its private Hindsight bank) |
| POST | `/api/auth/login` | Log in, returns a bearer token |
| GET | `/api/auth/me` | Current user and their memory-bank stats |
| POST | `/api/incidents/analyze` | Hindsight recall → Groq analysis |
| POST | `/api/incidents/{id}/resolve` | Save the confirmed resolution → Hindsight retain |
| GET | `/api/incidents` | Incident history |
| GET | `/api/incidents/{id}` | Incident detail |
| GET | `/api/incidents/{id}/memories` | What Hindsight recalled, plus the exact prompt sent to Groq |
| GET | `/api/health` | Groq config and Hindsight connectivity |

## Per-user isolation

* Every user has a stable `user_id`. Every incident row stores its owner, and every SQLite query filters by the authenticated `user_id`. Another user's incident returns 404.
* Every user has their **own Hindsight memory bank** (`<HINDSIGHT_BANK_ID>-u-<user_id>`). Hindsight banks are fully isolated from each other, so recall and retain can never see another user's memories. Nothing is ever cleared on login or signup.
* The browser only stores the session (`token`, `user_id`, `username`). The dashboard is re-mounted per `user_id`, so no previous user's data can remain in UI state.
* Databases from before accounts existed are migrated on startup: incidents created by `DEMO_USERNAME` are assigned to that account, which keeps the original `HINDSIGHT_BANK_ID` bank it wrote to.

## Setup

Requirements: Python 3.11+ and Node 20+.

```bash
cd backend
cp .env.example .env
```

Edit `backend/.env`:

```env
GROQ_API_KEY=gsk_...                       # https://console.groq.com/keys
GROQ_MODEL=openai/gpt-oss-120b             # any Groq chat model id
HINDSIGHT_API_KEY=...                      # Hindsight Cloud → Connect → API key
HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io
HINDSIGHT_BANK_ID=incident-response-agent  # prefix; each user gets their own bank
DEMO_USERNAME=admin
DEMO_PASSWORD=admin123
```

`HINDSIGHT_BASE_URL` is needed because the official Python client (`hindsight-client`) takes a `base_url` argument. The value above is the Hindsight Cloud endpoint.

API keys live only in `backend/.env`. That file is git-ignored and never reaches the browser, and all Groq and Hindsight calls go through FastAPI.

## Run

**Backend** (terminal 1):

```bash
cd backend
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (terminal 2):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and click **Create account**. Each account starts with an empty incident history and its own private Hindsight memory bank. Vite proxies `/api` to `http://127.0.0.1:8000`.

## Demo

Use a fresh Hindsight bank (or change `HINDSIGHT_BANK_ID`) so the first incident starts with no memory. The **Demo #1** and **Demo #2** buttons on the form fill in the incidents below.

### First incident: no memory yet

| Field | Value |
|---|---|
| Service | `payment-api` |
| Environment | production |
| Symptoms | Payment API latency is very high |
| Error Logs | Redis connection pool exhausted |

1. Click **Analyze Incident**. The **Hindsight Memory** panel shows *"no relevant previous incidents found in memory yet"*, and Groq analyzes the incident on its own.
2. Click **Yes, Save Resolution** and enter:
   * Root Cause: `Redis connection pool exhaustion`
   * Solution: `Increased Redis connection pool size from 50 to 150`
   * Outcome: `Latency returned to normal`
3. Click **Save to Hindsight**. The resolution is retained in the memory bank.

### Second incident: memory recalled

| Field | Value |
|---|---|
| Service | `payment-api` |
| Environment | production |
| Symptoms | Payment requests are slow again |
| Error Logs | Redis timeout warnings |
| Recent Changes | Traffic increased by 40% |

1. Click **Analyze Incident**. The **Hindsight Memory** panel now shows the previous incident with its root cause, solution, outcome and *why it is relevant* (same service, same environment, shared signals such as `redis`, and a relevance score).
2. The **AI Analysis** lists it under **Historical Matches**, with similarities (Redis, payment-api, latency) and differences (timeouts rather than pool exhaustion, and 40% more traffic, so a pool sized for the old load may be too small again). The recommended checks follow from that.
3. Click **Show exact prompt sent to Groq** to see that Groq received both the **CURRENT INCIDENT** and the **RELEVANT HISTORICAL INCIDENT MEMORY**.
4. Save the second resolution too. Each resolved incident adds to the memory, so later analyses have more history to draw on.

### Failure handling

* **Hindsight down, or wrong key:** the memory panel says *"Historical memory could not be retrieved"* and the analysis runs without history. The app never claims to have used memory when it didn't.
* **Retain fails:** the user sees an error and the incident is not marked as retained, so the save can be retried.
* **Groq timeout, rate limit, auth error or invalid output:** the user gets a clear error. Output is validated with Pydantic and retried once if it is invalid.

The agent only analyzes incidents and recommends actions. It never runs commands against production.
