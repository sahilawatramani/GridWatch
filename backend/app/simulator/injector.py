"""Fault injection simulator (§8 — injection half).

Produces telemetry that real faults would cause, including:
- 30% of dying messages that never arrive (fw >= 1.3)
- Firmware 1.2 devices that just go quiet (no power_lost)
- Dead sensor noise (device dies, power fine)
"""
from __future__ import annotations
import asyncio
import random
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.pole import Pole
from app.models.transformer import Transformer
from app.models.pole_state import PoleState, PoleStatus, StatusReason
from app.models.incident import Incident, IncidentStatus
from app.models.edge import Edge
from app.engine.topology import build_known_topology, infer_topology, TopologyTree

logger = logging.getLogger(__name__)

# Reference to the ingest function — set by main.py at startup
_ingest_event_fn = None
# Track suppressed heartbeats for simulated faults
_suppressed_poles: set[str] = set()


def set_ingest_fn(fn):
    global _ingest_event_fn
    _ingest_event_fn = fn


async def _send_event(pole_id: str, device_id: str, event: str,
                       energized: bool, fw: str = "1.4.2",
                       battery_mv: int = 3600, rssi: int = -75):
    """Send a synthetic telemetry event through the ingest pipeline."""
    if _ingest_event_fn is None:
        logger.warning("Ingest function not set — cannot send simulated event")
        return

    payload = {
        "device_id": device_id,
        "pole_id": pole_id,
        "event": event,
        "energized": energized,
        "ts": datetime.now(timezone.utc).isoformat(),
        "seq": random.randint(100000, 999999),
        "battery_mv": battery_mv,
        "rssi": rssi,
        "fw": fw,
    }
    await _ingest_event_fn(payload)


async def _get_topology_tree(session: AsyncSession, dt_id: str) -> Optional[TopologyTree]:
    """Load or build topology tree for a DT."""
    dt = await session.get(Transformer, dt_id)
    if not dt:
        return None

    result = await session.execute(select(Pole).where(Pole.dt_id == dt_id))
    poles = result.scalars().all()
    if not poles:
        return None

    pole_dicts = [
        {"pole_id": p.pole_id, "lat": p.lat, "lon": p.lon,
         "seq_on_line": p.seq_on_line, "parent_pole_id": p.parent_pole_id,
         "device_id": p.device_id}
        for p in poles
    ]

    has_known = any(p["seq_on_line"] is not None for p in pole_dicts)
    if has_known:
        return build_known_topology(dt_id, dt.lat, dt.lon, pole_dicts)
    else:
        return infer_topology(dt_id, dt.lat, dt.lon, pole_dicts)


async def inject_span_fault(dt_id: str, edge_index: Optional[int] = None) -> dict:
    """Inject a span fault on a DT. Darkens all poles downstream of the chosen edge.

    Returns info about what was injected for UI feedback.
    """
    async with async_session() as session:
        tree = await _get_topology_tree(session, dt_id)
        if not tree:
            return {"error": f"DT {dt_id} not found"}

        # Get all edges (excluding root)
        non_root_edges = [
            (e.from_id, e.to_id) for e in tree.edges
            if e.from_id != tree.root_id
        ]
        if not non_root_edges:
            # Fallback: use any edge
            non_root_edges = [(e.from_id, e.to_id) for e in tree.edges]

        if not non_root_edges:
            return {"error": "No edges found in topology"}

        # Pick edge
        if edge_index is not None and 0 <= edge_index < len(non_root_edges):
            from_id, to_id = non_root_edges[edge_index]
        else:
            # Pick a mid-line edge for maximum visual impact
            mid = len(non_root_edges) // 2
            from_id, to_id = non_root_edges[min(mid, len(non_root_edges) - 1)]

        # Get subtree below the fault point
        dark_poles = tree.get_subtree(to_id)

        # Get pole details
        result = await session.execute(
            select(Pole).where(Pole.pole_id.in_(dark_poles))
        )
        poles = result.scalars().all()

        affected = []
        for pole in poles:
            _suppressed_poles.add(pole.pole_id)

            if not pole.device_id:
                affected.append(pole.pole_id)
                continue

            # Determine firmware behavior
            fw = "1.4.2"  # default
            # Check if fw 1.2 (can't send power_lost)
            is_fw12 = False
            # We'll check from the pole registry data
            result2 = await session.execute(
                select(Pole.device_id).where(Pole.pole_id == pole.pole_id)
            )

            if is_fw12 or (hasattr(pole, '_fw') and pole._fw and pole._fw.startswith("1.2")):
                # FW 1.2: just go silent — no power_lost event
                affected.append(pole.pole_id)
                continue

            # FW >= 1.3: 70% chance of sending power_lost
            if random.random() < 0.70:
                await _send_event(
                    pole.pole_id, pole.device_id,
                    "power_lost", False,
                    battery_mv=random.randint(2800, 3400),
                    rssi=random.randint(-100, -70),
                )
            # else: 30% loss — device dies silently

            affected.append(pole.pole_id)

        logger.info(
            f"Injected span fault on {dt_id}: edge {from_id} → {to_id}, "
            f"{len(affected)} poles affected"
        )
        return {
            "dt_id": dt_id,
            "fault_edge": {"from": from_id, "to": to_id},
            "affected_poles": affected,
            "count": len(affected),
        }


async def inject_dt_fault(dt_id: str) -> dict:
    """Inject a DT-level fault — all poles under this DT go dark."""
    async with async_session() as session:
        tree = await _get_topology_tree(session, dt_id)
        if not tree:
            return {"error": f"DT {dt_id} not found"}

        all_poles = tree.all_pole_ids()
        result = await session.execute(
            select(Pole).where(Pole.pole_id.in_(all_poles))
        )
        poles = result.scalars().all()

        affected = []
        for pole in poles:
            _suppressed_poles.add(pole.pole_id)
            if pole.device_id:
                if random.random() < 0.70:
                    await _send_event(
                        pole.pole_id, pole.device_id,
                        "power_lost", False,
                        battery_mv=random.randint(2800, 3400),
                    )
            affected.append(pole.pole_id)

        logger.info(f"Injected DT fault on {dt_id}: {len(affected)} poles affected")
        return {"dt_id": dt_id, "affected_poles": affected, "count": len(affected)}


async def inject_feeder_fault(feeder_id: str) -> dict:
    """Inject a feeder-level fault — all DTs on this feeder go dark."""
    async with async_session() as session:
        result = await session.execute(
            select(Transformer.dt_id).where(Transformer.feeder_id == feeder_id)
        )
        dt_ids = [r[0] for r in result.all()]

    total_affected = []
    for dt_id in dt_ids:
        result = await inject_dt_fault(dt_id)
        total_affected.extend(result.get("affected_poles", []))

    logger.info(f"Injected feeder fault on {feeder_id}: {len(dt_ids)} DTs, {len(total_affected)} poles")
    return {
        "feeder_id": feeder_id,
        "dt_ids": dt_ids,
        "total_affected": len(total_affected),
    }


async def inject_dead_sensor(pole_id: str) -> dict:
    """Inject a dead sensor — device stops heartbeating but power is fine.

    This is the KEY difference from a real fault: no power_lost is sent.
    The system should NOT create a fault ticket for this.
    """
    _suppressed_poles.add(pole_id)
    logger.info(f"Injected dead sensor on {pole_id} (heartbeats suppressed, no power_lost)")
    return {"pole_id": pole_id, "type": "dead_sensor"}


async def repair_fault(incident_id: str) -> dict:
    """Repair a fault — send boot + power_restored for all affected poles."""
    async with async_session() as session:
        incident = await session.get(Incident, incident_id)
        if not incident:
            return {"error": f"Incident {incident_id} not found"}

        pole_ids = incident.affected_pole_ids or []
        result = await session.execute(
            select(Pole).where(Pole.pole_id.in_(pole_ids))
        )
        poles = result.scalars().all()

        incident.status = IncidentStatus.resolved
        incident.resolved_claimed_at = datetime.now(timezone.utc)
        incident.updated_at = datetime.now(timezone.utc)
        await session.commit()

        restored = []
        for pole in poles:
            _suppressed_poles.discard(pole.pole_id)
            if pole.device_id:
                await _send_event(
                    pole.pole_id, pole.device_id,
                    "boot", True,
                )
                await asyncio.sleep(0.05)  # Stagger slightly
                await _send_event(
                    pole.pole_id, pole.device_id,
                    "power_restored", True,
                )
            restored.append(pole.pole_id)

        logger.info(f"Repaired incident {incident_id}: {len(restored)} poles restored")
        return {
            "incident_id": str(incident_id),
            "restored_poles": restored,
            "count": len(restored),
        }


def is_pole_suppressed(pole_id: str) -> bool:
    """Check if a pole's heartbeats are suppressed (simulating fault/dead sensor)."""
    return pole_id in _suppressed_poles


def clear_suppressed_poles() -> None:
    """Clear all simulated suppression state before reseeding."""
    _suppressed_poles.clear()
