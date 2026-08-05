# GridWatch — Power Grid Fault Detection & Localization

A real-time fault detection and localization system for power distribution networks. Detects outages from pole-mounted sensor telemetry, pinpoints fault boundaries on the physical line, and raises exactly one ticket per fault with explainable confidence scoring.

## Live Demo

- **Operator console:** https://grid-watch-red.vercel.app/
- **Backend health check:** https://gridwatch-api.onrender.com/api/health
- **API reference:** https://gridwatch-api.onrender.com/docs
- **Demo video:** _Add the public or unlisted video link before submitting._

The backend runs on Render's free tier and can take around a minute to wake
after being idle. If the console initially shows no data, wait for the backend
to wake and refresh the page.

## Quick Start

```bash
# Clone and start
git clone <repo>
cd gridwatch
cp .env.example .env  # optionally configure a local LLM endpoint for AI briefings
docker compose up --build
```

Open:
- **Operator Console**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/health

The system auto-seeds ~3,000 poles across 40 DTs on 5 feeders on first startup. No manual setup needed.

## Deployment Model

For production, deploy the frontend separately from the backend:

- **Frontend**: Vercel â€” https://grid-watch-red.vercel.app/
- **Backend**: Render â€” https://gridwatch-api.onrender.com
- **Database**: Render Postgres, connected privately to the backend

Set `VITE_API_URL` in the frontend project to the public backend URL, for example `https://gridwatch-api.onrender.com/api`. The local Docker setup still uses the same-origin `/api` proxy.

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────┐
│   Devices    │────▶│  POST /api/ingest                 │
│  (simulated) │     │  ↓ staleness filter + dedup       │
└─────────────┘     │  ↓ asyncio.Queue                  │
                    │  ↓ batch writer                    │
                    │  ↓ debounce (30s window)           │
                    │  ↓ update pole state               │
                    │  ↓ build/infer topology (MST)      │
                    │  ↓ find fault boundaries (BFS)     │
                    │  ↓ group + dedup incidents         │
                    │  ↓ score confidence                │
                    │  ↓ create/update incident          │
                    │  ↓ SSE broadcast                   │
                    └──────────┬───────────────────────┘
                               │
                    ┌──────────▼───────────────────────┐
                    │  React Operator Console            │
                    │  • Leaflet map (poles + faults)    │
                    │  • Incident list + detail          │
                    │  • Confidence reasons              │
                    │  • AI crew briefings               │
                    │  • Fault simulator panel           │
                    └───────────────────────────────────┘
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **MST for topology inference** | Distribution poles form a tree. Geographic MST rooted at the DT is the natural estimator given only coordinates. |
| **BFS boundary detection** | Fault is on an edge, but sensors report on nodes. BFS from DT root finds live→dark boundaries. |
| **Debounce window (30s)** | Prevents flaky power_lost events from creating false tickets. |
| **SSE over WebSocket** | Simpler deployment, works through reverse proxies on free hosting tiers. |
| **No Redis** | At ~39 msg/s sustained, asyncio.Queue in-process is sufficient. Redis boundary: ~1,000 msg/s. |
| **Template fallback for AI briefings** | The optional local-LLM endpoint may be unavailable — system degrades gracefully. |
| **System-only verified/closed** | Prevents crew from marking tickets as resolved when telemetry disagrees. |

## Fault Types Detected

1. **Span fault** — wire break between two poles. Localized to specific edge.
2. **DT fault** — transformer failure. All poles under DT go dark.
3. **Feeder fault** — feeder-level failure. All DTs on feeder go dark.
4. **Dead sensor** (correctly NOT ticketed) — device failure, power is fine.

## Simulator

The built-in simulator lets you inject faults and observe detection in real-time:

| Button | What it does |
|--------|-------------|
| ⚡ Span Fault | Darkens poles downstream of a mid-line edge |
| 🔌 DT Fault | Darkens all poles under a DT |
| 💥 Feeder Fault | Darkens all DTs on a feeder |
| 📡 Dead Sensor | Stops heartbeats for one pole (should NOT create ticket) |
| 🔧 Repair | Sends restoration telemetry for an incident |

## Verification

The core detection-engine suite has 18 tests covering topology construction and
inference, span/DT detection, dead-sensor suppression, grouping, confidence,
lifecycle rules, stale events, and heartbeat timeouts. It was last run in the
backend container with all 18 passing:

```bash
docker compose run --rm backend python tests/test_engine.py
```

`backend/tests/load_test.py` is a repeatable 5,000-event burst test. Its result
is intentionally not claimed here because it has not been run against the
public deployment.

## Tech Stack

- **Backend**: Python 3.13, FastAPI, SQLAlchemy (async), PostgreSQL
- **Frontend**: React 18, Vite, Leaflet
- **AI**: Optional local LLM endpoint (default Phi-3/Ollama-compatible API), with template fallback
- **Infra**: Docker Compose

## Project Structure

```
gridwatch/
├── docker-compose.yml
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + lifespan
│   │   ├── config.py            # Settings from env
│   │   ├── database.py          # Async SQLAlchemy
│   │   ├── models/              # ORM models (7 tables)
│   │   ├── schemas/             # Pydantic validation
│   │   ├── api/                 # REST endpoints
│   │   ├── engine/              # Core algorithms
│   │   │   ├── topology.py      # MST inference
│   │   │   ├── boundary.py      # BFS fault detection
│   │   │   ├── confidence.py    # Scoring + reasons
│   │   │   ├── grouping.py      # Dedup across levels
│   │   │   ├── lifecycle.py     # Ticket state machine
│   │   │   ├── debounce.py      # Noise filtering
│   │   │   └── pipeline.py      # Orchestrator
│   │   ├── workers/             # Background tasks
│   │   ├── simulator/           # Seed + fault injection
│   │   └── services/            # AI briefing
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.jsx
    │   ├── index.css             # Design system
    │   ├── components/
    │   │   ├── MapView.jsx       # Leaflet map
    │   │   ├── IncidentList.jsx  # Sidebar
    │   │   ├── IncidentDetail.jsx
    │   │   └── SimulatorPanel.jsx
    │   └── utils/
    └── package.json
```

## License

Built for the Propel.ai 2026 assignment.
