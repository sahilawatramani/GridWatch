"""Pydantic schemas for API request/response validation."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


# ---------- Telemetry Ingest ----------

class TelemetryPayload(BaseModel):
    device_id: str
    pole_id: str
    event: str  # heartbeat, power_lost, power_restored, boot
    energized: bool
    ts: datetime
    seq: int
    battery_mv: Optional[int] = None
    rssi: Optional[int] = None
    fw: Optional[str] = None


# ---------- Incident ----------

class IncidentResponse(BaseModel):
    id: UUID
    fault_type: str
    dt_id: str
    feeder_id: str
    boundary_from_pole: Optional[str] = None
    boundary_to_pole: Optional[str] = None
    boundary_edge_source: Optional[str] = None
    boundary_edge_confidence: Optional[float] = None
    affected_pole_ids: list[str] = []
    lat: float
    lon: float
    pincode: Optional[str] = None
    confidence: float
    confidence_reason: Optional[str] = None
    status: str
    disputed: bool = False
    dispute_reason: Optional[str] = None
    households_estimate: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IncidentStatusUpdate(BaseModel):
    status: str  # acknowledged, crew_assigned, resolved


# ---------- Simulator ----------

class InjectSpanFaultRequest(BaseModel):
    dt_id: str
    edge_index: Optional[int] = None  # if None, pick a random mid-line edge


class InjectDtFaultRequest(BaseModel):
    dt_id: str


class InjectFeederFaultRequest(BaseModel):
    feeder_id: str


class InjectDeadSensorRequest(BaseModel):
    pole_id: str


class InjectScheduledOutageRequest(BaseModel):
    scope: str  # "feeder" or "dt"
    target_id: str
    start: datetime
    end: datetime
    reason: Optional[str] = "Load shedding"


class RepairRequest(BaseModel):
    incident_id: UUID


# ---------- Dashboard ----------

class DashboardStats(BaseModel):
    total_poles: int = 0
    poles_with_device: int = 0
    poles_live: int = 0
    poles_dark: int = 0
    poles_unknown: int = 0
    total_dts: int = 0
    total_feeders: int = 0
    active_incidents: int = 0
    acknowledged_incidents: int = 0
    resolved_today: int = 0


class PoleResponse(BaseModel):
    pole_id: str
    lat: float
    lon: float
    feeder_id: str
    dt_id: str
    device_id: Optional[str] = None
    status: Optional[str] = "unknown"
    pincode: Optional[str] = None

    model_config = {"from_attributes": True}


class TransformerResponse(BaseModel):
    dt_id: str
    feeder_id: str
    lat: float
    lon: float
    capacity_kva: int
    households_served: int

    model_config = {"from_attributes": True}


class EdgeResponse(BaseModel):
    dt_id: str
    from_pole_id: str
    to_pole_id: str
    source: str
    confidence: float
    distance_m: Optional[float] = None

    model_config = {"from_attributes": True}
