"""Dashboard API — stats, pole data, topology, and SSE stream."""
import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.database import get_db
from app.models.pole import Pole
from app.models.transformer import Transformer
from app.models.pole_state import PoleState, PoleStatus
from app.models.incident import Incident, IncidentStatus
from app.models.edge import Edge
from app.schemas import (
    DashboardStats, PoleResponse, TransformerResponse, EdgeResponse,
)
from app.engine.pipeline import subscribe_sse, unsubscribe_sse

router = APIRouter()


@router.get("/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Summary statistics for the dashboard header."""
    # Pole counts
    total_poles = (await db.execute(select(func.count(Pole.pole_id)))).scalar() or 0
    poles_with_device = (await db.execute(
        select(func.count(Pole.pole_id)).where(Pole.device_id.isnot(None))
    )).scalar() or 0

    # State counts
    live = (await db.execute(
        select(func.count(PoleState.pole_id)).where(PoleState.status == PoleStatus.live)
    )).scalar() or 0
    dark = (await db.execute(
        select(func.count(PoleState.pole_id)).where(PoleState.status == PoleStatus.dark)
    )).scalar() or 0
    unknown = total_poles - live - dark

    # DT and feeder counts
    total_dts = (await db.execute(select(func.count(Transformer.dt_id)))).scalar() or 0
    total_feeders = (await db.execute(
        select(func.count(func.distinct(Transformer.feeder_id)))
    )).scalar() or 0

    # Incident counts
    active = (await db.execute(
        select(func.count(Incident.id)).where(
            Incident.status.in_([
                IncidentStatus.detected, IncidentStatus.acknowledged,
                IncidentStatus.crew_assigned,
            ])
        )
    )).scalar() or 0
    acknowledged = (await db.execute(
        select(func.count(Incident.id)).where(Incident.status == IncidentStatus.acknowledged)
    )).scalar() or 0

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    resolved_today = (await db.execute(
        select(func.count(Incident.id)).where(
            Incident.status.in_([IncidentStatus.closed, IncidentStatus.verified]),
            Incident.updated_at >= today_start,
        )
    )).scalar() or 0

    return DashboardStats(
        total_poles=total_poles,
        poles_with_device=poles_with_device,
        poles_live=live,
        poles_dark=dark,
        poles_unknown=unknown,
        total_dts=total_dts,
        total_feeders=total_feeders,
        active_incidents=active,
        acknowledged_incidents=acknowledged,
        resolved_today=resolved_today,
    )


@router.get("/poles")
async def list_poles(
    dt_id: str = None,
    feeder_id: str = None,
    db: AsyncSession = Depends(get_db),
):
    """List poles with their current status."""
    query = select(Pole, PoleState.status).outerjoin(
        PoleState, Pole.pole_id == PoleState.pole_id
    )
    if dt_id:
        query = query.where(Pole.dt_id == dt_id)
    if feeder_id:
        query = query.where(Pole.feeder_id == feeder_id)

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "pole_id": pole.pole_id,
            "lat": pole.lat,
            "lon": pole.lon,
            "feeder_id": pole.feeder_id,
            "dt_id": pole.dt_id,
            "device_id": pole.device_id,
            "status": status.value if status else "unknown",
            "pincode": pole.pincode,
        }
        for pole, status in rows
    ]


@router.get("/transformers")
async def list_transformers(
    feeder_id: str = None,
    db: AsyncSession = Depends(get_db),
):
    """List distribution transformers."""
    query = select(Transformer)
    if feeder_id:
        query = query.where(Transformer.feeder_id == feeder_id)
    result = await db.execute(query)
    return [
        TransformerResponse.model_validate(dt)
        for dt in result.scalars().all()
    ]


@router.get("/feeders")
async def list_feeders(db: AsyncSession = Depends(get_db)):
    """List all feeder IDs."""
    result = await db.execute(
        select(Transformer.feeder_id).distinct()
    )
    return [{"feeder_id": r[0]} for r in result.all()]


@router.get("/topology/{dt_id}")
async def get_topology(dt_id: str, db: AsyncSession = Depends(get_db)):
    """Get the topology edges for a DT."""
    result = await db.execute(
        select(Edge).where(Edge.dt_id == dt_id)
    )
    edges = result.scalars().all()
    return [EdgeResponse.model_validate(e) for e in edges]


@router.get("/edges")
async def get_all_edges(db: AsyncSession = Depends(get_db)):
    """Get all topology edges to draw the network map."""
    result = await db.execute(select(Edge))
    edges = result.scalars().all()
    return [EdgeResponse.model_validate(e) for e in edges]


@router.get("/events/stream")
async def sse_stream(request: Request):
    """SSE stream for real-time UI updates."""
    queue = subscribe_sse()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {"event": "update", "data": msg}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            unsubscribe_sse(queue)

    return EventSourceResponse(event_generator())


@router.get("/scheduled-outages")
async def list_scheduled_outages(db: AsyncSession = Depends(get_db)):
    """Mock scheduled outage feed matching 02-data-and-systems §4 format."""
    from app.models.scheduled_outage import ScheduledOutage
    result = await db.execute(select(ScheduledOutage))
    outages = result.scalars().all()
    return [
        {
            "id": o.id,
            "scope": o.scope,
            "target_id": o.target_id,
            "start": o.start.isoformat() if o.start else None,
            "end": o.end.isoformat() if o.end else None,
            "reason": o.reason,
        }
        for o in outages
    ]
