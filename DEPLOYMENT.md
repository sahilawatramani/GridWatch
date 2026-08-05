# Deployment Guide — GridWatch

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
   - `GEMINI_API_KEY` optional.
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

## Troubleshooting

### "Connection refused" on startup
The backend waits for Postgres to be healthy. If you see connection errors, postgres may still be starting:
```bash
docker compose logs postgres  # Check if PG is ready
docker compose restart backend  # Retry
```

### Frontend can't reach API
The Vite dev server proxies `/api` to `http://backend:8000`. In production, set `VITE_API_URL` in Vercel so the frontend points at the public backend URL.

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
