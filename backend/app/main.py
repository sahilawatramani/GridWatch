"""GridWatch — Power Grid Fault Detection System.

FastAPI application with lifespan managing:
- Database migrations (auto on startup)
- Synthetic data seeding (G3 compliance)
- Background workers (ingest, heartbeat watchdog, verification watchdog, heartbeat sim)
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, async_session, Base
from app.api import ingest, incidents, simulator, dashboard
from app.workers.ingest_worker import ingest_worker, set_detection_fn, enqueue_event
from app.workers.heartbeat_watchdog import heartbeat_watchdog, set_detection_fn as set_hb_detection_fn
from app.workers.verification_watchdog import verification_watchdog, check_auto_close_detected
from app.workers.heartbeat_sim import heartbeat_simulator
from app.engine.pipeline import run_detection_for_dt
from app.simulator.injector import set_ingest_fn
from app.services.ai_briefing import generate_briefing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("GridWatch starting up...")

    # Create tables (Alembic would be better, but this is simpler for docker compose up)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed data if database is empty
    async with async_session() as session:
        from sqlalchemy import select, func
        from app.models.transformer import Transformer
        count = (await session.execute(select(func.count(Transformer.dt_id)))).scalar()
        if count == 0:
            logger.info("Database empty — seeding synthetic data...")
            from app.simulator.seed import seed_network
            await seed_network(session)
            logger.info("Seed complete")

    # Wire up cross-module references
    set_detection_fn(run_detection_for_dt)
    set_hb_detection_fn(run_detection_for_dt)

    async def _ingest_via_queue(payload):
        await enqueue_event(payload)

    set_ingest_fn(_ingest_via_queue)

    # Start background workers
    tasks = [
        asyncio.create_task(ingest_worker(), name="ingest_worker"),
        asyncio.create_task(heartbeat_watchdog(), name="heartbeat_watchdog"),
        asyncio.create_task(verification_watchdog(), name="verification_watchdog"),
    ]

    if settings.heartbeat_sim_enabled:
        tasks.append(asyncio.create_task(heartbeat_simulator(), name="heartbeat_sim"))

    # Periodic auto-close check
    async def periodic_auto_close():
        while True:
            await asyncio.sleep(5)
            try:
                await check_auto_close_detected()
            except Exception as e:
                logger.error(f"Auto-close check error: {e}")

    tasks.append(asyncio.create_task(periodic_auto_close(), name="auto_close"))

    logger.info("GridWatch ready — all workers started")
    yield

    # Shutdown
    logger.info("GridWatch shutting down...")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await engine.dispose()


app = FastAPI(
    title="GridWatch",
    description="Power Grid Fault Detection & Localization System",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(ingest.router, prefix="/api", tags=["Ingest"])
app.include_router(incidents.router, prefix="/api", tags=["Incidents"])
app.include_router(simulator.router, prefix="/api", tags=["Simulator"])
app.include_router(dashboard.router, prefix="/api", tags=["Dashboard"])


# AI briefing endpoint (alongside incidents)
@app.post("/api/incidents/{incident_id}/briefing")
async def get_briefing(incident_id: str):
    """Generate AI crew briefing for an incident."""
    from sqlalchemy import select
    from app.models.incident import Incident
    from uuid import UUID

    async with async_session() as session:
        incident = await session.get(Incident, UUID(incident_id))
        if not incident:
            from fastapi import HTTPException
            raise HTTPException(404, "Incident not found")

        data = {
            "fault_type": incident.fault_type.value,
            "lat": incident.lat,
            "lon": incident.lon,
            "pincode": incident.pincode,
            "dt_id": incident.dt_id,
            "feeder_id": incident.feeder_id,
            "affected_pole_ids": incident.affected_pole_ids or [],
            "households_estimate": incident.households_estimate,
            "confidence": incident.confidence,
            "confidence_reason": incident.confidence_reason,
            "boundary_from_pole": incident.boundary_from_pole,
            "boundary_to_pole": incident.boundary_to_pole,
            "boundary_edge_source": incident.boundary_edge_source,
            "created_at": str(incident.created_at),
        }
        result = await generate_briefing(data)
        return result


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "gridwatch"}
