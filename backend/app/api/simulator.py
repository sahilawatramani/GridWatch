"""Simulator API — fault injection endpoints for the reviewer (§8)."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session
from app.schemas import (
    InjectSpanFaultRequest, InjectDtFaultRequest, InjectFeederFaultRequest,
    InjectDeadSensorRequest, InjectScheduledOutageRequest, RepairRequest,
)
from app.simulator.injector import (
    inject_span_fault, inject_dt_fault, inject_feeder_fault,
    inject_dead_sensor, repair_fault,
)
from app.simulator.seed import seed_network
from app.models.scheduled_outage import ScheduledOutage
from app.runtime_control import set_maintenance_mode
from app.workers.ingest_worker import clear_debounce_timers
from app.simulator.injector import clear_suppressed_poles

router = APIRouter(prefix="/simulator")


@router.post("/seed")
async def reseed():
    """Regenerate all synthetic data. Wipes and recreates."""
    set_maintenance_mode(True)
    try:
        clear_debounce_timers()
        clear_suppressed_poles()
        async with async_session() as session:
            result = await seed_network(session)
        return {"status": "seeded", **result}
    finally:
        set_maintenance_mode(False)


@router.post("/inject-span-fault")
async def api_inject_span_fault(body: InjectSpanFaultRequest):
    """Inject a span fault on a DT line."""
    result = await inject_span_fault(body.dt_id, body.edge_index)
    return result


@router.post("/inject-dt-fault")
async def api_inject_dt_fault(body: InjectDtFaultRequest):
    """Inject a DT-level fault (all poles under DT go dark)."""
    result = await inject_dt_fault(body.dt_id)
    return result


@router.post("/inject-feeder-fault")
async def api_inject_feeder_fault(body: InjectFeederFaultRequest):
    """Inject a feeder-level fault (all DTs on feeder go dark)."""
    result = await inject_feeder_fault(body.feeder_id)
    return result


@router.post("/inject-dead-sensor")
async def api_inject_dead_sensor(body: InjectDeadSensorRequest):
    """Kill a sensor (stops heartbeats, NO power_lost — power is fine).
    System should NOT create a fault ticket.
    """
    result = await inject_dead_sensor(body.pole_id)
    return result


@router.post("/inject-scheduled-outage")
async def api_inject_scheduled_outage(body: InjectScheduledOutageRequest):
    """Register a scheduled outage. System should suppress fault detection."""
    async with async_session() as session:
        outage = ScheduledOutage(
            id=f"SO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            scope=body.scope,
            target_id=body.target_id,
            start=body.start,
            end=body.end,
            reason=body.reason,
        )
        session.add(outage)
        await session.commit()
    return {"status": "scheduled", "id": outage.id}


@router.post("/repair")
async def api_repair(body: RepairRequest):
    """Repair a fault — sends restoration telemetry for affected poles."""
    result = await repair_fault(str(body.incident_id))
    return result
