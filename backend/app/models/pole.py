"""Pole model — each distribution pole in the network."""
from sqlalchemy import Column, String, Float, Integer, Index
from app.database import Base


class Pole(Base):
    __tablename__ = "poles"

    pole_id = Column(String, primary_key=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    feeder_id = Column(String, nullable=False)
    dt_id = Column(String, nullable=False)
    seq_on_line = Column(Integer, nullable=True)       # NULL for ~60% of DTs
    parent_pole_id = Column(String, nullable=True)     # NULL wherever seq_on_line is NULL
    pole_type = Column(String, nullable=True)
    ward = Column(String, nullable=True)
    pincode = Column(String, nullable=True)            # NULL for ~3%
    device_id = Column(String, nullable=True)          # NULL for ~9% (no device)

    __table_args__ = (
        Index("ix_poles_dt_id", "dt_id"),
        Index("ix_poles_feeder_id", "feeder_id"),
        Index("ix_poles_device_id", "device_id"),
    )
