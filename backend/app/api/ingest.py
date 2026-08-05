"""Telemetry ingest endpoint (§7).

POST /api/ingest — accepts telemetry, validates, deduplicates, enqueues.
Returns 200 OK immediately (idempotent).
"""
from fastapi import APIRouter, Request
from datetime import datetime, timezone

from app.schemas import TelemetryPayload
from app.workers.ingest_worker import enqueue_event

router = APIRouter()


@router.post("/ingest", status_code=200)
async def ingest_telemetry(payload: TelemetryPayload):
    """Accept a telemetry event from a pole device.

    Idempotent: duplicate (device_id, seq) pairs are silently ignored.
    """
    await enqueue_event(payload.model_dump(mode="json"))
    return {"status": "ok"}


@router.post("/ingest/batch", status_code=200)
async def ingest_batch(payloads: list[TelemetryPayload]):
    """Accept a batch of telemetry events."""
    for payload in payloads:
        await enqueue_event(payload.model_dump(mode="json"))
    return {"status": "ok", "count": len(payloads)}
