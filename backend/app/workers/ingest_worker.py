"""Ingest worker — batched processing of telemetry events (§7).

Accepts events via asyncio.Queue, processes in batches, updates pole states,
and triggers the detection pipeline when states change.

Throughput target: sustained 500 msg/s, burst 5,000 in 10s.
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.telemetry import TelemetryEvent, EventType
from app.models.pole_state import PoleState, PoleStatus, StatusReason
from app.config import settings
from app.engine.debounce import should_trigger_dark, should_trigger_live, is_stale_event
from app.runtime_control import is_maintenance_mode

logger = logging.getLogger(__name__)

# In-process event queue (replaces Redis for this scale)
event_queue: asyncio.Queue = asyncio.Queue(maxsize=50000)

# Debounce timers: {pole_id: asyncio.TimerHandle}
_debounce_timers: dict[str, asyncio.TimerHandle] = {}

# Reference to detection pipeline — set at startup
_detection_fn = None


def set_detection_fn(fn):
    global _detection_fn
    _detection_fn = fn


async def enqueue_event(payload: dict):
    """Enqueue a telemetry event for batched processing."""
    if is_maintenance_mode():
        return
    try:
        event_queue.put_nowait(payload)
    except asyncio.QueueFull:
        logger.warning("Ingest queue full — dropping event")


async def ingest_worker():
    """Background worker draining the event queue in batches."""
    logger.info("Ingest worker started")
    while True:
        try:
            if is_maintenance_mode():
                await asyncio.sleep(0.2)
                continue

            batch = []
            # Pull up to batch_size events, with timeout
            try:
                first = await asyncio.wait_for(
                    event_queue.get(), timeout=1.0
                )
                batch.append(first)
            except asyncio.TimeoutError:
                continue

            # Drain more if available
            while len(batch) < settings.ingest_batch_size:
                try:
                    item = event_queue.get_nowait()
                    batch.append(item)
                except asyncio.QueueEmpty:
                    break

            if batch:
                await _process_batch(batch)

        except Exception as e:
            logger.exception(f"Ingest worker error: {e}")
            await asyncio.sleep(1)


async def _process_batch(batch: list[dict]):
    """Process a batch of telemetry events."""
    if is_maintenance_mode():
        return

    now = datetime.now(timezone.utc)
    affected_dts = set()

    async with async_session() as session:
        for payload in batch:
            try:
                device_id = payload["device_id"]
                pole_id = payload["pole_id"]
                event_type = payload["event"]
                energized = payload["energized"]
                device_ts = payload.get("ts")
                seq = payload.get("seq", 0)

                if isinstance(device_ts, str):
                    device_ts = datetime.fromisoformat(device_ts.replace("Z", "+00:00"))

                # Dedup check: (device_id, seq) unique
                existing = await session.execute(
                    select(TelemetryEvent.id).where(
                        TelemetryEvent.device_id == device_id,
                        TelemetryEvent.seq == seq,
                    ).limit(1)
                )
                if existing.first():
                    continue  # Duplicate — skip

                # Staleness filter
                if is_stale_event(device_ts, now):
                    # Check if pole is currently live
                    state = await session.get(PoleState, pole_id)
                    if state and state.status == PoleStatus.live:
                        logger.debug(f"Stale event from {device_id} ignored (pole {pole_id} is live)")
                        continue

                # Insert telemetry event
                event = TelemetryEvent(
                    id=uuid.uuid4(),
                    device_id=device_id,
                    pole_id=pole_id,
                    event=EventType(event_type),
                    energized=energized,
                    device_ts=device_ts,
                    received_ts=now,
                    seq=seq,
                    battery_mv=payload.get("battery_mv"),
                    rssi=payload.get("rssi"),
                    fw=payload.get("fw"),
                )
                session.add(event)

                # Update pole state
                dt_id = await _update_pole_state(
                    session, pole_id, event_type, energized, now,
                    payload.get("battery_mv"), payload.get("rssi"),
                )
                if dt_id:
                    affected_dts.add(dt_id)

            except Exception as e:
                logger.error(f"Error processing event: {e}")
                continue

        await session.commit()

    # Trigger detection for affected DTs
    for dt_id in affected_dts:
        if _detection_fn:
            asyncio.create_task(_detection_fn(dt_id))


async def _update_pole_state(
    session, pole_id: str, event_type: str, energized: bool,
    now: datetime, battery_mv: Optional[int], rssi: Optional[int],
) -> Optional[str]:
    """Update pole state based on incoming event. Returns dt_id if state changed."""
    from app.models.pole import Pole

    state = await session.get(PoleState, pole_id)
    if not state:
        return None

    pole = await session.get(Pole, pole_id)
    dt_id = pole.dt_id if pole else None

    old_status = state.status
    state.last_event_ts = now
    if battery_mv is not None:
        state.last_battery_mv = str(battery_mv)
    if rssi is not None:
        state.last_rssi = str(rssi)

    if should_trigger_live(event_type, energized):
        state.status = PoleStatus.live
        state.reason = StatusReason.reported_live
        state.last_heartbeat_ts = now
        # Cancel debounce timer
        _cancel_debounce(pole_id)
        if old_status != PoleStatus.live:
            return dt_id

    elif should_trigger_dark(event_type, energized):
        # Don't flip immediately — schedule debounce check
        _schedule_debounce(pole_id, dt_id)
        # Still update the event timestamp
        return None  # Don't trigger detection yet — wait for debounce

    elif event_type == "heartbeat" and energized:
        state.status = PoleStatus.live
        state.reason = StatusReason.reported_live
        state.last_heartbeat_ts = now
        _cancel_debounce(pole_id)

    return None


def _schedule_debounce(pole_id: str, dt_id: Optional[str]):
    """Schedule a delayed state check after debounce window."""
    _cancel_debounce(pole_id)  # Cancel any existing timer

    loop = asyncio.get_event_loop()
    handle = loop.call_later(
        settings.debounce_window_s,
        lambda: asyncio.create_task(_debounce_check(pole_id, dt_id)),
    )
    _debounce_timers[pole_id] = handle


def _cancel_debounce(pole_id: str):
    """Cancel a pending debounce timer."""
    handle = _debounce_timers.pop(pole_id, None)
    if handle:
        handle.cancel()


def clear_debounce_timers() -> None:
    """Cancel all pending debounce timers. Used before reseeding."""
    for handle in _debounce_timers.values():
        handle.cancel()
    _debounce_timers.clear()


async def _debounce_check(pole_id: str, dt_id: Optional[str]):
    """Called after debounce window — check if pole is still dark."""
    try:
        logger.info(f"_debounce_check started for pole {pole_id} on dt {dt_id}")
        _debounce_timers.pop(pole_id, None)

        async with async_session() as session:
            state = await session.get(PoleState, pole_id)
            if not state:
                logger.warning(f"No PoleState found for {pole_id}")
                return

            # Timer wasn't cancelled, which means no live events were received during debounce
            # Pole still not live → mark as dark
            state.status = PoleStatus.dark
            state.reason = StatusReason.reported_dark
            await session.commit()
            logger.info(f"Pole {pole_id} marked as dark after debounce")

        # Trigger detection pipeline for this DT
        if dt_id and _detection_fn:
            logger.info(f"Triggering detection pipeline for DT {dt_id}")
            asyncio.create_task(_detection_fn(dt_id))
        else:
            logger.warning(f"Cannot trigger detection: dt_id={dt_id}, _detection_fn={_detection_fn}")
    except Exception as e:
        logger.exception(f"Error in _debounce_check for {pole_id}: {e}")
