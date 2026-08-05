"""Distribution Transformer model."""
from sqlalchemy import Column, String, Float, Integer
from app.database import Base


class Transformer(Base):
    __tablename__ = "transformers"

    dt_id = Column(String, primary_key=True)
    feeder_id = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    capacity_kva = Column(Integer, nullable=False)
    households_served = Column(Integer, nullable=False)
