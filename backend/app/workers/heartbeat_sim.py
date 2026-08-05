"""Background heartbeat simulator — keeps the system alive with periodic heartbeats.

Sends heartbeats for all poles with devices every ~15 minutes (±45s jitter),
matching the real device behavior from 02-data-and-systems §2.
"""
import asyncio
import random
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import async_session
from app.models.pole import Pole
from app.models.pole_state import PoleState, PoleStatus
from app.simulator.injector import is_pole_suppressed
from app.workers.ingest_worker import enqueue_event
from app.runtime_control import is_maintenance_mode

logger = logging.getLogger(__name__)


async def heartbeat_simulator():
    """Send periodic heartbeats for all live poles with devices."""
    logger.info("Heartbeat simulator started")
    # Wait a bit for seed to complete
    await asyncio.sleep(5)

    while True:
        try:
            if is_maintenance_mode():
                await asyncio.sleep(1)
                continue
            await _send_heartbeats()
            # Sleep for heartbeat interval with jitter
            interval = 900 + random.randint(-45, 45)  # 15 min ± 45s
            # For simulation speed, use 60s intervals
            await asyncio.sleep(60)
        except Exception as e:
            logger.exception(f"Heartbeat simulator error: {e}")
            await asyncio.sleep(10)


async def _send_heartbeats():
    """Send heartbeat events for all live, non-suppressed poles."""
    async with async_session() as session:
        result = await session.execute(
            select(Pole.pole_id, Pole.device_id).where(
                Pole.device_id.isnot(None)
            )
        )
        poles = result.all()

    count = 0
    for pole_id, device_id in poles:
        if is_pole_suppressed(pole_id):
            continue

        # ~4% of fleet offline at any moment (random skip)
        if random.random() < 0.04:
            continue

        await enqueue_event({
            "device_id": device_id,
            "pole_id": pole_id,
            "event": "heartbeat",
            "energized": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "seq": random.randint(100000, 999999),
            "battery_mv": random.randint(3400, 3800),
            "rssi": random.randint(-95, -60),
            "fw": "1.4.2",
        })
        count += 1

        # Stagger to avoid burst
        if count % 100 == 0:
            await asyncio.sleep(0.1)

    logger.debug(f"Sent {count} heartbeats")
