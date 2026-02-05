
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MetricIn(BaseModel):
    ts: datetime = Field(..., description="Timestamp of the metric point (ISO 8601)")
    metric_name: str = Field(..., min_length=1, description="Metric name, e.g. p95_latency_ms")
    value: float = Field(..., description="Metric value")


class EventIn(BaseModel):
    ts: datetime = Field(..., description="Timestamp of the event (ISO 8601)")
    event_type: str = Field(..., min_length=1, description="Event type, e.g. deploy, feature_flag")
    meta: Optional[Dict[str, Any]] = Field(default=None, description="Arbitrary event metadata")


class IngestRequest(BaseModel):
    incident_id: Optional[str] = Field(default=None,
                                       description="Optional client-provided incident ID")
    name: Optional[str] = Field(default=None, description="Human-readable name, e.g. incident_456")
    source: Optional[str] = Field(default=None, description="Where this came from, e.g. prod, ci")
    meta: Optional[Dict[str, Any]] = Field(default=None, description="Optional incident metadata")

    metrics: List[MetricIn] = Field(default_factory=list)
    events: List[EventIn] = Field(default_factory=list)


class IngestResponse(BaseModel):
    incident_id: str
    metrics_ingested: int
    events_ingested: int


class AnomalyOut(BaseModel):
    metric_name: str
    ts: datetime
    value: float
    baseline_mean: float
    baseline_std: float
    z_score: float


class CauseOut(BaseModel):
    event_type: str
    ts: datetime
    meta: Optional[Dict[str, Any]] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


class EpisodeOut(BaseModel):
    metric_name: str
    start_ts: datetime
    end_ts: datetime
    baseline_mean: float
    baseline_std: float
    peak_value: float
    peak_z_score: float
    percent_change: float


class AnalysisResponse(BaseModel):
    incident_id: str
    anomalies: List[AnomalyOut]
    episodes: List[EpisodeOut]
    likely_causes: List[CauseOut]
