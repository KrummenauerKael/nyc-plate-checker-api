from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey, func, Date
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()

# Cache-aside lookup key: one row per plate+state+type combo, with fetched_at for TTL checks
class Plate(Base):
    __tablename__ = 'plates'

    id = Column(Integer, primary_key=True)
    plate = Column(String, nullable=False)
    state = Column(String, nullable=False)
    plate_type = Column(String, nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=True) 

# One row per violation for a given plate, keyed by summons number (upsert target)
class Violation(Base):
    __tablename__ = 'violations'

    id = Column(Integer, primary_key=True)
    summons_number = Column(String, nullable=False, unique=True)
    plate_id = Column(Integer, ForeignKey('plates.id'), nullable=False)
    amount_due = Column(Numeric, nullable=True)
    total_amount = Column(Numeric, nullable=True)
    violation_date = Column(Date, nullable=True)
    raw_data = Column(JSONB, nullable=True)

# Timestamped log of each query made for a plate (for history/analytics, not TTL)
class Lookup(Base):
    __tablename__ = 'lookups'

    id = Column(Integer, primary_key=True)
    plate_id = Column(Integer, ForeignKey('plates.id'), nullable=False)
    queried_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

