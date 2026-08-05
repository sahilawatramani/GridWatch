# Deployment Guide — GridWatch

## Current Public Deployment

- Operator console: https://grid-watch-red.vercel.app/
- Backend: https://gridwatch-api.onrender.com
- Health check: https://gridwatch-api.onrender.com/api/health
- API documentation: https://gridwatch-api.onrender.com/docs

The Render backend is on a free instance and can cold-start after inactivity.
Wait for it to wake, then refresh the Vercel console if the first request fails.

## Local Development (Docker Compose)

```bash
# Prerequisites: Docker & Docker Compose installed
git clone <repo>
cd gridwatch
cp .env.example .env

# Start all services
docker compose up --build

# Access:
# - Frontend: http://localhost:3000
# - Backend API: http://localhost:8000
# - API Docs: http://localhost:8000/docs
```

On first startup, the backend will:
1. Create all database tables (auto-migration)
2. Seed ~3,000 poles across 40 DTs on 5 feeders
3. Start background heartbeat simulation

## Local Development (Without Docker)

### Backend
```bash
cd backend
pip install -r requirements.txt
# Start PostgreSQL separately (e.g., local install or Docker):
docker run -d --name gridwatch-pg -e POSTGRES_DB=gridwatch -e POSTGRES_USER=gridwatch -e POSTGRES_PASSWORD=gridwatch -p 5432:5432 postgres:16-alpine

# Set environment
export DATABASE_URL=postgresql+asyncpg://gridwatch:gridwatch@localhost:5432/gridwatch
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev -- --port 3000
```

## Cloud Deployment (Recommended Split)

### 1) Backend on Render or Railway
1. Create a new Web Service from the GitHub repo.
2. Point it at the backend service folder if your platform supports a root directory, or use the backend Dockerfile.
3. Set environment variables:
   - `DATABASE_URL` required, from managed Postgres.
   - `LOCAL_LLM_URL` and `LOCAL_LLM_MODEL` optional; the briefing feature uses a template when no local LLM is available.
   - `HEARTBEAT_SIM_ENABLED=true` recommended for the demo.
4. Deploy the backend first and note its public API URL, such as `https://gridwatch-api.onrender.com`.

### 2) Frontend on Vercel
1. Import the same GitHub repo into Vercel.
2. Set the root directory to `frontend`.
3. Add environment variable:
   - `VITE_API_URL=https://gridwatch-api.onrender.com/api`
4. Build command: `npm run build`
5. Output directory: `dist`
6. Deploy the frontend and verify the console loads data from the backend URL.

### 3) Database
Use the managed PostgreSQL service from the same backend host. The backend still performs table creation and seeding on startup.

### SSE Through Proxy
SSE requires the proxy to NOT buffer responses. Most PaaS platforms handle this correctly for `text/event-stream` content type. If SSE isn't working:

```
# For nginx reverse proxy, add:
proxy_buffering off;
proxy_cache off;
proxy_set_header Connection '';
```

## Environment Variables

Copy `.env.example` to `.env` for local Docker development. Vercel must be
configured with `VITE_API_URL=https://gridwatch-api.onrender.com/api` for
production. Do not commit database credentials or any local-LLM credentials.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | Yes outside Docker | Docker Postgres URL | Async SQLAlchemy connection URL. Render's `postgresql://` URL is normalized to `postgresql+asyncpg://` by the application. |
| `GEMINI_API_KEY` | No | empty | Reserved configuration; the current briefing implementation does not call Gemini directly. |
| `LOCAL_LLM_URL` | No | `http://host.docker.internal:11434/api/generate` | Optional Ollama-compatible endpoint for AI crew briefings. The template is used if unreachable. |
| `LOCAL_LLM_MODEL` | No | `phi3` | Model name sent to the local-LLM endpoint. |
| `VITE_API_URL` | Yes on Vercel | `/api` | Public API base URL, including `/api`. |
| `DEBOUNCE_WINDOW_S` | No | `30` | Wait before treating a power-loss report as dark. |
| `HEARTBEAT_TIMEOUT_S` | No | `1200` | Silence duration before the watchdog marks a pole stale/dark. |
| `CANDIDATE_RADIUS_M` | No | `150` | Maximum candidate-edge distance for inferred topology. |
| `RESTORATION_THRESHOLD` | No | `0.95` | Fraction of affected poles that must be live for verification. |
| `HEARTBEAT_SIM_ENABLED` | No | `true` | Runs the synthetic heartbeat simulator for the demo. |
| `HEARTBEAT_INTERVAL_S` | No | `900` | Synthetic heartbeat interval. |
| `HEARTBEAT_JITTER_S` | No | `45` | Synthetic heartbeat jitter. |
| `WATCHDOG_INTERVAL_S` | No | `60` | Heartbeat-watchdog scan interval. |
| `VERIFICATION_INTERVAL_S` | No | `30` | Resolved-ticket verification scan interval. |
| `STALE_EVENT_THRESHOLD_S` | No | `600` | Threshold used when evaluating delayed events. |
| `SUSTAIN_WINDOW_S` | No | `60` | Restoration sustain-window configuration. |
| `OUTAGE_GRACE_BEFORE_M` | No | `15` | Planned-outage early-start grace. |
| `OUTAGE_OVERRUN_M` | No | `40` | Planned-outage late-restoration grace. |
| `INGEST_BATCH_SIZE` | No | `500` | Maximum events drained per ingest-worker batch. |
| `INGEST_BATCH_TIMEOUT_MS` | No | `100` | Reserved batching configuration. |

## Troubleshooting

### "Connection refused" on startup
The backend waits for Postgres to be healthy. If you see connection errors, postgres may still be starting:
```bash
docker compose logs postgres  # Check if PG is ready
docker compose restart backend  # Retry
```

### Frontend can't reach API
The Vite dev server proxies `/api` to `http://backend:8000`. In production, set `VITE_API_URL` in Vercel so the frontend points at the public backend URL.

### Render reports it cannot open `/opt/venv/bin/python`
The final image was using a distroless Python entrypoint, which interpreted the
virtual-environment Python path as a script. The production Dockerfile uses the
same `python:3.13-slim` base image for build and runtime, so the copied virtual
environment has a compatible Python executable. Rebuild/redeploy after changing
the Dockerfile.

### Render health check times out on port 10000
Render assigns the service port through `PORT`; it is not always 8000. The
Docker command reads `PORT` and defaults to 8000 only for local use. Ensure the
health-check path is `/api/health` and do not hard-code the Render port.

### Render Postgres connection fails with a driver error
Render supplies `connectionString` in the `postgresql://...` form, whereas the
async engine requires `postgresql+asyncpg://...`. The application normalizes
that URL on startup. Keep `DATABASE_URL` referenced from the Render database in
`render.yaml`; do not paste credentials into the repository.

### Stale data / want to reset
```bash
# Via API:
curl -X POST http://localhost:8000/api/simulator/seed

# Or nuke volumes:
docker compose down -v
docker compose up --build
```

### SSE not working
1. Check browser DevTools Network tab for `/api/events/stream`
2. Should show `text/event-stream` content type
3. If behind Cloudflare/nginx, disable response buffering

### Frontend loads but shows no data on Vercel
1. Confirm `VITE_API_URL` includes the backend `/api` path, for example `https://gridwatch-api.onrender.com/api`
2. Rebuild the Vercel deployment after changing environment variables
3. Open the backend `/api/health` URL directly to confirm the API is live

### "Module not found" errors
```bash
# Backend
pip install -r requirements.txt

# Frontend
cd frontend && npm install
```
