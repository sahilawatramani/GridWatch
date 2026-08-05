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

## Cloud Deployment (Railway / Render)

### Railway (Recommended)
1. Create a new project from GitHub repo
2. Railway auto-detects `docker-compose.yml`
3. Add environment variables:
   - `GEMINI_API_KEY` (optional)
   - `DATABASE_URL` is auto-provisioned by Railway's Postgres plugin
4. Deploy

### Render
1. Create a new Web Service from GitHub
2. **Backend**: Set build command to `pip install -r requirements.txt`, start command to `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. **Frontend**: Create a Static Site, build command `npm run build`, publish directory `dist`
4. Add Render Postgres
5. Set `DATABASE_URL` environment variable

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
The Vite dev server proxies `/api` to `http://backend:8000`. In production, configure your reverse proxy or set `VITE_API_URL`.

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

### "Module not found" errors
```bash
# Backend
pip install -r requirements.txt

# Frontend
cd frontend && npm install
```
