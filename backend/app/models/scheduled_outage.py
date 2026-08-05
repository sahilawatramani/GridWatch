"""ScheduledOutage model — mock feed for planned load shedding."""
from sqlalchemy import Column, String, DateTime, Text
from app.database import Base


class ScheduledOutage(Base):
    __tablename__ = "scheduled_outages"

    id = Column(String, primary_key=True)          # e.g. "SO-2026-07-29-014"
    scope = Column(String, nullable=False)          # "feeder" or "dt"
    target_id = Column(String, nullable=False)      # feeder_id or dt_id
    start = Column(DateTime(timezone=True), nullable=False)
    end = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text, nullable=True)
