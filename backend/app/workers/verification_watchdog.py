"""Verification watchdog (§6) — auto-verifies restored incidents.

Runs every 30s. Checks incidents in 'resolved' status:
- If ≥95% of affected poles are live (sustained 60s+) → auto-verify → close
- If not → flag as disputed (crew claimed fixed but telemetry disagrees)
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.incident import Incident, IncidentStatus
from app.models.pole_state import PoleState, PoleStatus
from app.models.pole import Pole
from app.engine.lifecycle import can_auto_verify
from app.engine.pipeline import broadcast_sse
from app.config import settings
from app.runtime_control import is_maintenance_mode

logger = logging.getLogger(__name__)


async def verification_watchdog():
    """Periodic verification of resolved incidents."""
    logger.info("Verification watchdog started")
    while True:
        try:
            if is_maintenance_mode():
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(settings.verification_interval_s)
            await _check_resolved_incidents()
        except Exception as e:
            logger.exception(f"Verification watchdog error: {e}")
            await asyncio.sleep(5)


async def _check_resolved_incidents():
    """Check all incidents in 'resolved' state for telemetry verification."""
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        result = await session.execute(
            select(Incident).where(Incident.status == IncidentStatus.resolved)
        )
        incidents = result.scalars().all()

        for incident in incidents:
            pole_ids = incident.affected_pole_ids or []
            if not pole_ids:
                continue

            total = len(pole_ids)

            poles_result = await session.execute(
                select(Pole).where(Pole.pole_id.in_(pole_ids))
            )
            poles = poles_result.scalars().all()
            instrumented_count = sum(1 for p in poles if p.device_id is not None)

            # Count live poles
            states_result = await session.execute(
                select(PoleState).where(PoleState.pole_id.in_(pole_ids))
            )
            states = states_result.scalars().all()

            live_count = sum(1 for s in states if s.status == PoleStatus.live)

            if can_auto_verify(live_count, instrumented_count, settings.restoration_threshold):
                # Check sustained window
                resolved_at = incident.resolved_claimed_at or incident.updated_at
                elapsed = (now - resolved_at).total_seconds()

                if elapsed >= settings.sustain_window_s:
                    # Auto-verify and close
                    incident.status = IncidentStatus.verified
                    incident.verified_at = now
                    incident.updated_at = now
                    # Immediately close after verification
                    incident.status = IncidentStatus.closed
                    incident.disputed = False
                    incident.dispute_reason = None

                    logger.info(
                        f"Incident {incident.id} auto-verified and closed: "
                        f"{live_count}/{total} poles live"
                    )
                    await broadcast_sse("incident_closed", {
                        "id": str(incident.id),
                        "live_count": live_count,
                        "total": total,
                    })
            else:
                # Telemetry disagrees with crew's resolution claim
                dark_count = total - live_count
                if not incident.disputed:
                    incident.disputed = True
                    incident.dispute_reason = (
                        f"{dark_count} of {total} poles still dark after crew marked resolved"
                    )
                    incident.updated_at = now
                    logger.warning(
                        f"Incident {incident.id} disputed: {dark_count}/{total} poles still dark"
                    )
                    await broadcast_sse("incident_disputed", {
                        "id": str(incident.id),
                        "dark_count": dark_count,
                        "total": total,
                    })

        await session.commit()


async def check_auto_close_detected():
    """Also check 'detected' incidents — if all poles come back live, auto-close.
    This handles the case where a fault self-heals (e.g., temporary contact issue).
    """
    async with async_session() as session:
        result = await session.execute(
            select(Incident).where(
                Incident.status.in_([
                    IncidentStatus.detected,
                    IncidentStatus.acknowledged,
                    IncidentStatus.crew_assigned,
                ])
            )
        )
        incidents = result.scalars().all()
        now = datetime.now(timezone.utc)

        for incident in incidents:
            pole_ids = incident.affected_pole_ids or []
            if not pole_ids:
                continue

            poles_result = await session.execute(
                select(Pole).where(Pole.pole_id.in_(pole_ids))
            )
            poles = poles_result.scalars().all()
            instrumented_count = sum(1 for p in poles if p.device_id is not None)

            states_result = await session.execute(
                select(PoleState).where(PoleState.pole_id.in_(pole_ids))
            )
            states = states_result.scalars().all()
            live_count = sum(1 for s in states if s.status == PoleStatus.live)

            if can_auto_verify(live_count, instrumented_count):
                incident.status = IncidentStatus.verified
                incident.verified_at = now
                incident.status = IncidentStatus.closed
                incident.updated_at = now
                logger.info(f"Incident {incident.id} auto-closed (self-healed)")
                await broadcast_sse("incident_closed", {
                    "id": str(incident.id),
                })

        await session.commit()
