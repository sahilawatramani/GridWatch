"""Edge model — materialized topology (known or inferred)."""
import enum
from sqlalchemy import Column, String, Float, Enum, Index
from app.database import Base


class EdgeSource(str, enum.Enum):
    known = "known"
    inferred = "inferred"


class Edge(Base):
    __tablename__ = "edges"

    # Composite PK: (dt_id, from_pole_id/NULL, to_pole_id)
    dt_id = Column(String, primary_key=True)
    from_pole_id = Column(String, primary_key=True, default="__DT__")  # "__DT__" = root edge from DT itself
    to_pole_id = Column(String, primary_key=True)
    source = Column(Enum(EdgeSource, name="edge_source", create_constraint=True), nullable=False)
    confidence = Column(Float, nullable=False, default=1.0)
    distance_m = Column(Float, nullable=True)  # haversine distance of this span

    __table_args__ = (
        Index("ix_edges_dt_id", "dt_id"),
        Index("ix_edges_to_pole", "to_pole_id"),
    )
