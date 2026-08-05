"""Debounce and noise filtering (§3).

Design: a power_lost event doesn't immediately create a fault candidate.
Wait DEBOUNCE_WINDOW and re-check state. This prevents flaky messages
from generating false tickets.

The heartbeat watchdog catches firmware-1.2 devices that go silent
instead of sending power_lost, AND catches dead-modem-while-live noise.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import settings


def should_trigger_dark(
    event_type: str,
    energized: bool,
) -> bool:
    """Check if an event should schedule a debounce check (potential dark)."""
    return event_type == "power_lost" or (not energized and event_type != "boot")


def should_trigger_live(
    event_type: str,
    energized: bool,
) -> bool:
    """Check if an event confirms the pole is live (cancels debounce)."""
    return event_type in ("power_restored", "heartbeat", "boot") and energized


def is_stale_event(device_ts: datetime, received_ts: datetime) -> bool:
    """Check if an event is stale (arrived much later than it was generated).

    Handles 6-hour retries from offline devices that send very stale
    power_lost messages long after the event.
    """
    if device_ts.tzinfo is None:
        device_ts = device_ts.replace(tzinfo=timezone.utc)
    if received_ts.tzinfo is None:
        received_ts = received_ts.replace(tzinfo=timezone.utc)

    threshold = timedelta(seconds=settings.stale_event_threshold_s)
    return (received_ts - device_ts) > threshold


def is_heartbeat_timed_out(
    last_heartbeat_ts: Optional[datetime],
    now: Optional[datetime] = None,
) -> bool:
    """Check if a device has missed its heartbeat window."""
    if last_heartbeat_ts is None:
        return True  # never heard from → treat as timed out

    if now is None:
        now = datetime.now(timezone.utc)

    if last_heartbeat_ts.tzinfo is None:
        last_heartbeat_ts = last_heartbeat_ts.replace(tzinfo=timezone.utc)

    timeout = timedelta(seconds=settings.heartbeat_timeout_s)
    return (now - last_heartbeat_ts) > timeout


def is_scheduled_outage(
    dt_id: str,
    feeder_id: str,
    outages: list[dict],
    now: Optional[datetime] = None,
) -> tuple[bool, bool]:
    """Check if a fault candidate falls within a scheduled outage window.

    Returns:
        (is_suppressed, near_boundary):
        - is_suppressed: True if within grace window → suppress the fault
        - near_boundary: True if within 15 min of window edge (for confidence penalty)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    grace_before = timedelta(minutes=settings.outage_grace_before_m)
    overrun = timedelta(minutes=settings.outage_overrun_m)
    double_overrun = overrun * 2  # Promote to real candidate at 2× overrun

    for outage in outages:
        scope = outage.get("scope", "")
        target = outage.get("target_id", "")

        # Check if this outage applies to our DT/feeder
        matches = False
        if scope == "feeder" and target == feeder_id:
            matches = True
        elif scope == "dt" and target == dt_id:
            matches = True

        if not matches:
            continue

        start = outage["start"]
        end = outage["end"]
        if isinstance(start, str):
            start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        if isinstance(end, str):
            end = datetime.fromisoformat(end.replace("Z", "+00:00"))

        effective_start = start - grace_before
        effective_end = end + overrun
        promote_deadline = end + double_overrun

        if effective_start <= now <= effective_end:
            # Within grace window — suppress
            # But check if near boundary
            near_edge = (
                (now - effective_start) < timedelta(minutes=15) or
                (effective_end - now) < timedelta(minutes=15)
            )
            return True, near_edge

        if effective_end < now <= promote_deadline:
            # Past overrun but within 2× — near boundary, lower confidence
            return False, True

    return False, False
