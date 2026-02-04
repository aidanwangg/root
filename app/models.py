
from sqlalchemy import Column, String, DateTime, Float, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.db import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=uuid_str)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # optional: useful metadata
    name = Column(String, nullable=True)          # e.g., "incident_456" or "build_123"
    source = Column(String, nullable=True)        # e.g., "ci", "prod"
    meta = Column("metadata", JSON, nullable=True)

    metrics = relationship("MetricPoint", back_populates="incident", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="incident", cascade="all, delete-orphan")


class MetricPoint(Base):
    __tablename__ = "metric_points"

    id = Column(String, primary_key=True, default=uuid_str)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)

    ts = Column(DateTime, nullable=False)         # timestamp
    metric_name = Column(String, nullable=False)  # e.g., "p95_latency_ms"
    value = Column(Float, nullable=False)

    incident = relationship("Incident", back_populates="metrics")


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=uuid_str)
    incident_id = Column(String, ForeignKey("incidents.id"), nullable=False)

    ts = Column(DateTime, nullable=False)
    event_type = Column(String, nullable=False)   # e.g., "deploy", "feature_flag"
    meta = Column("metadata", JSON, nullable=True)

    incident = relationship("Incident", back_populates="events")


# Helpful indexes for speed
Index("ix_metric_incident_ts", MetricPoint.incident_id, MetricPoint.ts)
Index("ix_event_incident_ts", Event.incident_id, Event.ts)
Index("ix_metric_incident_name_ts", MetricPoint.incident_id, MetricPoint.metric_name, MetricPoint.ts)
