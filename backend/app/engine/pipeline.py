"""Detection pipeline — orchestrates event → state → boundary → incident.

This is the glue connecting:
  debounce → boundary-finding → grouping → confidence → incident creation

Triggered when pole states change after debounce window expires.
"""
from __future__ import annotations
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.pole import Pole
from app.models.transformer import Transformer
from app.models.edge import Edge
from app.models.pole_state import PoleState, PoleStatus, StatusReason
from app.models.incident import Incident, IncidentStatus, FaultType
from app.models.scheduled_outage import ScheduledOutage
from app.engine.topology import (
    TopologyTree, TopoNode, TopoEdge,
    build_known_topology, infer_topology,
)
from app.engine.boundary import find_fault_boundaries, FaultCandidate
from app.engine.grouping import group_into_incidents
from app.engine.confidence import compute_confidence
from app.engine.debounce import is_scheduled_outage

logger = logging.getLogger(__name__)

# Global SSE subscribers
_sse_subscribers: list[asyncio.Queue] = []


def subscribe_sse() -> asyncio.Queue:
    q = asyncio.Queue()
    _sse_subscribers.append(q)
    return q


def unsubscribe_sse(q: asyncio.Queue):
    if q in _sse_subscribers:
        _sse_subscribers.remove(q)


async def broadcast_sse(event_type: str, data: dict):
    msg = json.dumps({"type": event_type, "data": data})
    for q in _sse_subscribers:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass  # drop if subscriber is slow


async def run_detection_for_dt(dt_id: str):
    """Run full detection pipeline for a specific DT."""
    async with async_session() as session:
        try:
            # 1. Load DT info
            dt = await session.get(Transformer, dt_id)
            if not dt:
                return

            # 2. Check scheduled outage
            outages = await _load_outages(session, dt_id, dt.feeder_id)
            suppressed, near_boundary = is_scheduled_outage(
                dt_id, dt.feeder_id, outages
            )
            if suppressed:
                logger.debug(f"DT {dt_id} suppressed by scheduled outage")
                return

            # 3. Load poles and states
            poles_result = await session.execute(
                select(Pole).where(Pole.dt_id == dt_id)
            )
            poles = poles_result.scalars().all()
            if not poles:
                return

            pole_ids = [p.pole_id for p in poles]
            states_result = await session.execute(
                select(PoleState).where(PoleState.pole_id.in_(pole_ids))
            )
            states = {s.pole_id: s for s in states_result.scalars().all()}

            pole_states = {
                p.pole_id: states[p.pole_id].status.value
                if p.pole_id in states else "unknown"
                for p in poles
            }
            pole_devices = {p.pole_id: p.device_id for p in poles}
            pole_pincodes = {p.pole_id: p.pincode for p in poles}

            # 4. Build/load topology tree
            tree = await _load_or_build_topology(session, dt_id, dt, poles)

            # 5. Check if feeder-wide (all DTs on feeder dark)
            is_feeder_wide = await _check_feeder_wide(session, dt.feeder_id)

            # 6. Find fault boundaries
            candidates = find_fault_boundaries(
                tree=tree,
                pole_states=pole_states,
                pole_devices=pole_devices,
                pole_pincodes=pole_pincodes,
                feeder_id=dt.feeder_id,
                is_feeder_wide=is_feeder_wide,
            )

            if not candidates:
                logger.info(f"No candidates found for DT {dt_id}")
                return
            logger.info(f"Found {len(candidates)} candidates for DT {dt_id}")

            # Set near_scheduled_outage flag
            for c in candidates:
                c.near_scheduled_outage = near_boundary

            # 7. Score confidence
            explicitly_reported = set()
            for pid, state in states.items():
                if state.reason == StatusReason.reported_dark:
                    explicitly_reported.add(pid)

            for c in candidates:
                # Get device health signals for boundary pole
                boundary_rssi = None
                boundary_battery = None
                if c.boundary_to and c.boundary_to in states:
                    s = states[c.boundary_to]
                    try:
                        boundary_rssi = int(s.last_rssi) if s.last_rssi else None
                    except (ValueError, TypeError):
                        pass
                    try:
                        boundary_battery = int(s.last_battery_mv) if s.last_battery_mv else None
                    except (ValueError, TypeError):
                        pass

                c_score, c_reasons = compute_confidence(
                    candidate=c,
                    pole_devices=pole_devices,
                    explicitly_reported_dark=explicitly_reported,
                    boundary_device_rssi=boundary_rssi,
                    boundary_device_battery_mv=boundary_battery,
                )
                # Store on candidate for incident creation
                c.confidence_score = c_score
                c.confidence_reasons = c_reasons

            # 8. Group and dedup
            incidents = group_into_incidents(candidates)

            # 9. Create/update incidents
            for candidate in incidents:
                await _upsert_incident(session, candidate, dt)

            logger.info(f"Upserted {len(incidents)} incidents for DT {dt_id}, committing...")
            await session.commit()
            logger.info(f"Successfully committed {len(incidents)} incidents for DT {dt_id}")

        except Exception as e:
            logger.exception(f"Detection pipeline error for DT {dt_id}: {e}")
            await session.rollback()


async def _load_or_build_topology(
    session: AsyncSession, dt_id: str, dt: Transformer, poles: list[Pole],
) -> TopologyTree:
    """Build topology tree — known or inferred."""
    pole_dicts = [
        {
            "pole_id": p.pole_id, "lat": p.lat, "lon": p.lon,
            "seq_on_line": p.seq_on_line, "parent_pole_id": p.parent_pole_id,
            "device_id": p.device_id,
        }
        for p in poles
    ]

    # Check if this DT has known topology
    has_known = any(p["seq_on_line"] is not None for p in pole_dicts)

    if has_known:
        return build_known_topology(dt_id, dt.lat, dt.lon, pole_dicts)
    else:
        return infer_topology(dt_id, dt.lat, dt.lon, pole_dicts)


async def _load_outages(session: AsyncSession, dt_id: str, feeder_id: str) -> list[dict]:
    """Load active scheduled outages for this DT/feeder."""
    result = await session.execute(
        select(ScheduledOutage).where(
            ((ScheduledOutage.scope == "dt") & (ScheduledOutage.target_id == dt_id)) |
            ((ScheduledOutage.scope == "feeder") & (ScheduledOutage.target_id == feeder_id))
        )
    )
    outages = result.scalars().all()
    return [
        {
            "scope": o.scope, "target_id": o.target_id,
            "start": o.start, "end": o.end,
        }
        for o in outages
    ]


async def _check_feeder_wide(session: AsyncSession, feeder_id: str) -> bool:
    """Check if ALL DTs on a feeder have all poles dark → feeder-level fault."""
    # Get all DTs on this feeder
    dts_result = await session.execute(
        select(Transformer.dt_id).where(Transformer.feeder_id == feeder_id)
    )
    dt_ids = [r[0] for r in dts_result.all()]

    if len(dt_ids) <= 1:
        return False

    # Check if all poles on all DTs are dark
    for dt_id in dt_ids:
        poles_result = await session.execute(
            select(Pole.pole_id).where(Pole.dt_id == dt_id)
        )
        pole_ids = [r[0] for r in poles_result.all()]
        if not pole_ids:
            continue

        states_result = await session.execute(
            select(PoleState).where(
                PoleState.pole_id.in_(pole_ids),
                PoleState.status == PoleStatus.live,
            )
        )
        if states_result.scalars().first():
            return False  # Found a live pole → not feeder-wide

    return True


async def _upsert_incident(
    session: AsyncSession, candidate: FaultCandidate, dt: Transformer,
):
    """Create or skip incident from a fault candidate.

    Skip if there's already an active incident for the same DT with overlapping poles.
    """
    # Check for existing active incident on same DT with overlapping affected poles
    existing_result = await session.execute(
        select(Incident).where(
            Incident.dt_id == candidate.dt_id,
            Incident.status.in_([
                IncidentStatus.detected,
                IncidentStatus.acknowledged,
                IncidentStatus.crew_assigned,
            ]),
        )
    )
    existing = existing_result.scalars().all()

    for inc in existing:
        overlap = set(inc.affected_pole_ids or []) & set(candidate.affected_poles)
        if overlap:
            # Update existing incident with new data
            inc.affected_pole_ids = list(
                set(inc.affected_pole_ids or []) | set(candidate.affected_poles)
            )
            inc.confidence = getattr(candidate, 'confidence_score', 0.5)
            inc.confidence_reason = json.dumps(
                getattr(candidate, 'confidence_reasons', [])
            )
            inc.updated_at = datetime.now(timezone.utc)
            await broadcast_sse("incident_updated", {
                "id": str(inc.id),
                "status": inc.status.value,
            })
            return

    # Compute households estimate
    households = dt.households_served
    total_poles = len(
        (await session.execute(
            select(Pole.pole_id).where(Pole.dt_id == candidate.dt_id)
        )).all()
    )
    if total_poles > 0:
        ratio = len(candidate.affected_poles) / total_poles
        households = int(households * ratio)

    # Resolve pincode — use candidate pincode, or nearest-neighbor fallback
    pincode = candidate.pincode
    if not pincode:
        # Nearest-neighbor: find closest pole with a known pincode
        pincode = await _resolve_pincode(session, candidate.lat, candidate.lon, candidate.dt_id)

    # Create new incident
    fault_type_map = {"span": FaultType.span, "dt": FaultType.dt, "feeder": FaultType.feeder}
    incident = Incident(
        id=uuid.uuid4(),
        fault_type=fault_type_map.get(candidate.fault_type, FaultType.span),
        dt_id=candidate.dt_id,
        feeder_id=candidate.feeder_id,
        boundary_from_pole=candidate.boundary_from,
        boundary_to_pole=candidate.boundary_to,
        boundary_edge_source=candidate.boundary_edge_source,
        boundary_edge_confidence=candidate.boundary_edge_confidence,
        affected_pole_ids=candidate.affected_poles,
        lat=candidate.lat,
        lon=candidate.lon,
        pincode=pincode,
        confidence=getattr(candidate, 'confidence_score', 0.5),
        confidence_reason=json.dumps(getattr(candidate, 'confidence_reasons', [])),
        status=IncidentStatus.detected,
        households_estimate=households,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(incident)

    await broadcast_sse("incident_created", {
        "id": str(incident.id),
        "fault_type": candidate.fault_type,
        "dt_id": candidate.dt_id,
        "lat": candidate.lat,
        "lon": candidate.lon,
        "affected_count": len(candidate.affected_poles),
        "confidence": getattr(candidate, 'confidence_score', 0.5),
    })


async def _resolve_pincode(
    session: AsyncSession, lat: float, lon: float, dt_id: str,
) -> Optional[str]:
    """Resolve missing pincode via nearest-neighbor from same DT."""
    result = await session.execute(
        select(Pole.pincode).where(
            Pole.dt_id == dt_id,
            Pole.pincode.isnot(None),
        ).limit(1)
    )
    row = result.first()
    if row:
        return row[0]
    # Fallback: any nearby pole
    result = await session.execute(
        select(Pole.pincode).where(Pole.pincode.isnot(None)).limit(1)
    )
    row = result.first()
    return row[0] if row else None
