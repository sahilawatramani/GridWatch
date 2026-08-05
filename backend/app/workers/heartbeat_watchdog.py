"""Heartbeat watchdog — catches silent device failures (§3).

Runs every 60s. Catches:
1. Firmware 1.2 devices that can't send power_lost — they just stop heartbeating
2. Dead modems where the device died while power is fine

This ALONE can't distinguish "device died, power fine" from "device died because
power died" for an isolated pole. That's what boundary-finding resolves — by
checking whether children are also dark.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_

from app.database import async_session
from app.models.pole import Pole
from app.models.pole_state import PoleState, PoleStatus, StatusReason
from app.engine.debounce import is_heartbeat_timed_out
from app.config import settings
from app.runtime_control import is_maintenance_mode

logger = logging.getLogger(__name__)

_detection_fn = None


def set_detection_fn(fn):
    global _detection_fn
    _detection_fn = fn


async def heartbeat_watchdog():
    """Periodic scan for devices that stopped heartbeating."""
    logger.info("Heartbeat watchdog started")
    while True:
        try:
            if is_maintenance_mode():
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(settings.watchdog_interval_s)
            await _scan_heartbeats()
        except Exception as e:
            logger.exception(f"Heartbeat watchdog error: {e}")
            await asyncio.sleep(5)


async def _scan_heartbeats():
    """Scan all poles with devices for heartbeat timeouts."""
    now = datetime.now(timezone.utc)
    affected_dts = set()

    async with async_session() as session:
        # Find all poles with devices that are currently live
        result = await session.execute(
            select(PoleState, Pole.dt_id).join(
                Pole, PoleState.pole_id == Pole.pole_id
            ).where(
                Pole.device_id.isnot(None),
                PoleState.status == PoleStatus.live,
            )
        )

        changed = False
        for state, dt_id in result.all():
            if is_heartbeat_timed_out(state.last_heartbeat_ts, now):
                state.status = PoleStatus.dark
                state.reason = StatusReason.heartbeat_timeout
                affected_dts.add(dt_id)
                changed = True

        if changed:
            await session.commit()

    # Trigger detection for affected DTs
    for dt_id in affected_dts:
        if _detection_fn:
            asyncio.create_task(_detection_fn(dt_id))
