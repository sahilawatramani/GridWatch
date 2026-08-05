"""TelemetryEvent model — raw events from pole devices."""
import enum
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Enum, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
import uuid

from app.database import Base


class EventType(str, enum.Enum):
    heartbeat = "heartbeat"
    power_lost = "power_lost"
    power_restored = "power_restored"
    boot = "boot"


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String, nullable=False)
    pole_id = Column(String, nullable=False)
    event = Column(Enum(EventType, name="event_type", create_constraint=True), nullable=False)
    energized = Column(Boolean, nullable=False)
    device_ts = Column(DateTime(timezone=True), nullable=False)   # untrusted, ±90s skew
    received_ts = Column(DateTime(timezone=True), nullable=False) # server clock, trustworthy
    seq = Column(Integer, nullable=False)                         # monotonic per device, resets on boot
    battery_mv = Column(Integer, nullable=True)
    rssi = Column(Integer, nullable=True)
    fw = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("device_id", "seq", name="uq_telemetry_device_seq"),
        Index("ix_telemetry_pole_received", "pole_id", "received_ts"),
        Index("ix_telemetry_device_id", "device_id"),
    )
