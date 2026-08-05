"""Incident model — fault tickets with lifecycle."""
import enum
import uuid
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Enum, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, ARRAY
from sqlalchemy import Index, func
from app.database import Base


class FaultType(str, enum.Enum):
    span = "span"
    dt = "dt"
    feeder = "feeder"
    sensor_only = "sensor_only"


class IncidentStatus(str, enum.Enum):
    detected = "detected"
    acknowledged = "acknowledged"
    crew_assigned = "crew_assigned"
    resolved = "resolved"
    verified = "verified"
    closed = "closed"


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fault_type = Column(Enum(FaultType, name="fault_type", create_constraint=True), nullable=False)
    dt_id = Column(String, nullable=False)
    feeder_id = Column(String, nullable=False)

    # Boundary edge (the specific span, if resolvable)
    boundary_from_pole = Column(String, nullable=True)
    boundary_to_pole = Column(String, nullable=True)
    boundary_edge_source = Column(String, nullable=True)   # known / inferred
    boundary_edge_confidence = Column(Float, nullable=True)

    # Affected poles
    affected_pole_ids = Column(ARRAY(String), nullable=False, default=[])

    # Location for navigation
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    pincode = Column(String, nullable=True)

    # Confidence
    confidence = Column(Float, nullable=False, default=1.0)
    confidence_reason = Column(Text, nullable=True)  # JSON-serialized list of reason strings

    # Lifecycle
    status = Column(
        Enum(IncidentStatus, name="incident_status", create_constraint=True),
        nullable=False,
        default=IncidentStatus.detected,
    )
    disputed = Column(Boolean, nullable=False, default=False)
    dispute_reason = Column(Text, nullable=True)
    resolved_claimed_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)

    # Metadata
    households_estimate = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_incidents_status_created", "status", "created_at"),
        Index("ix_incidents_dt_id", "dt_id"),
        Index("ix_incidents_feeder_id", "feeder_id"),
    )
