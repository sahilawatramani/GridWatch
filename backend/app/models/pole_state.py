"""PoleState model — current derived liveness per pole."""
import enum
from sqlalchemy import Column, String, DateTime, Enum, Index
from app.database import Base


class PoleStatus(str, enum.Enum):
    live = "live"
    dark = "dark"
    unknown = "unknown"


class StatusReason(str, enum.Enum):
    reported_dark = "reported_dark"        # explicit power_lost received
    heartbeat_timeout = "heartbeat_timeout" # device stopped heartbeating
    no_data = "no_data"                    # no device or no data ever received
    reported_live = "reported_live"        # explicit heartbeat/power_restored


class PoleState(Base):
    __tablename__ = "pole_states"

    pole_id = Column(String, primary_key=True)
    status = Column(Enum(PoleStatus, name="pole_status", create_constraint=True), nullable=False, default=PoleStatus.unknown)
    last_event_ts = Column(DateTime(timezone=True), nullable=True)
    last_heartbeat_ts = Column(DateTime(timezone=True), nullable=True)
    reason = Column(Enum(StatusReason, name="status_reason", create_constraint=True), nullable=False, default=StatusReason.no_data)
    last_battery_mv = Column(String, nullable=True)
    last_rssi = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_pole_states_status", "status"),
    )
