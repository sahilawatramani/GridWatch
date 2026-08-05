"""Incident management API (§6).

CRUD + lifecycle transitions. Enforces that verified/closed are system-only.
"""
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.incident import Incident, IncidentStatus
from app.schemas import IncidentResponse, IncidentStatusUpdate
from app.engine.lifecycle import validate_transition, LifecycleError

router = APIRouter()


@router.get("/incidents", response_model=list[IncidentResponse])
async def list_incidents(
    status: str = None,
    feeder_id: str = None,
    dt_id: str = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """List incidents with optional filters."""
    query = select(Incident).order_by(Incident.created_at.desc()).limit(limit)

    if status:
        query = query.where(Incident.status == IncidentStatus(status))
    if feeder_id:
        query = query.where(Incident.feeder_id == feeder_id)
    if dt_id:
        query = query.where(Incident.dt_id == dt_id)

    result = await db.execute(query)
    incidents = result.scalars().all()

    return [_to_response(i) for i in incidents]


@router.get("/incidents/active", response_model=list[IncidentResponse])
async def list_active_incidents(db: AsyncSession = Depends(get_db)):
    """List all active (non-closed) incidents."""
    result = await db.execute(
        select(Incident).where(
            Incident.status.notin_([IncidentStatus.closed, IncidentStatus.verified])
        ).order_by(Incident.created_at.desc())
    )
    return [_to_response(i) for i in result.scalars().all()]


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a single incident by ID."""
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _to_response(incident)


@router.patch("/incidents/{incident_id}/status")
async def update_incident_status(
    incident_id: UUID,
    body: IncidentStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Transition an incident's status.

    Enforces lifecycle rules:
    - verified/closed can NEVER be set via API — only by verification_watchdog
    - Valid manual transitions: acknowledged, crew_assigned, resolved
    """
    incident = await db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    try:
        validate_transition(incident.status.value, body.status, actor="human")
    except LifecycleError as e:
        raise HTTPException(status_code=403, detail=str(e))

    incident.status = IncidentStatus(body.status)
    incident.updated_at = datetime.now(timezone.utc)

    if body.status == "resolved":
        incident.resolved_claimed_at = datetime.now(timezone.utc)

    await db.commit()
    return _to_response(incident)


@router.get("/incidents/stats/summary")
async def incident_stats(db: AsyncSession = Depends(get_db)):
    """Summary statistics for dashboard."""
    result = await db.execute(
        select(
            Incident.status,
            func.count(Incident.id),
        ).group_by(Incident.status)
    )
    stats = {row[0].value: row[1] for row in result.all()}
    return {
        "active": stats.get("detected", 0) + stats.get("acknowledged", 0) + stats.get("crew_assigned", 0),
        "detected": stats.get("detected", 0),
        "acknowledged": stats.get("acknowledged", 0),
        "crew_assigned": stats.get("crew_assigned", 0),
        "resolved": stats.get("resolved", 0),
        "closed": stats.get("closed", 0) + stats.get("verified", 0),
    }


def _to_response(incident: Incident) -> IncidentResponse:
    return IncidentResponse(
        id=incident.id,
        fault_type=incident.fault_type.value,
        dt_id=incident.dt_id,
        feeder_id=incident.feeder_id,
        boundary_from_pole=incident.boundary_from_pole,
        boundary_to_pole=incident.boundary_to_pole,
        boundary_edge_source=incident.boundary_edge_source,
        boundary_edge_confidence=incident.boundary_edge_confidence,
        affected_pole_ids=incident.affected_pole_ids or [],
        lat=incident.lat,
        lon=incident.lon,
        pincode=incident.pincode,
        confidence=incident.confidence,
        confidence_reason=incident.confidence_reason,
        status=incident.status.value,
        disputed=incident.disputed,
        dispute_reason=incident.dispute_reason,
        households_estimate=incident.households_estimate,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
    )
