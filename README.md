# GridWatch — Power Grid Fault Detection & Localization

A real-time fault detection and localization system for power distribution networks. Detects outages from pole-mounted sensor telemetry, pinpoints fault boundaries on the physical line, and raises exactly one ticket per fault with explainable confidence scoring.

## Quick Start

```bash
# Clone and start
git clone <repo>
cd gridwatch
cp .env.example .env  # optionally add GEMINI_API_KEY
docker compose up --build
```

Open:
- **Operator Console**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/health

The system auto-seeds ~3,000 poles across 40 DTs on 5 feeders on first startup. No manual setup needed.

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
| **Template fallback for AI briefings** | Gemini API may be unavailable — system degrades gracefully. |
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

## Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy (async), PostgreSQL
- **Frontend**: React 18, Vite, Leaflet
- **AI**: Google Gemini Flash (optional, with template fallback)
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
