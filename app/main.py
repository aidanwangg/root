
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal, engine
from app import models
from app.schemas import IngestRequest, IngestResponse

from collections import defaultdict
from datetime import timedelta
import math

from app.schemas import AnalysisResponse, AnomalyOut, CauseOut, EpisodeOut


app = FastAPI()


# --- DB session per request ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def startup():
    # check that DB is reachable
    with engine.connect() as conn:
        print("✅ Database connection successful")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResponse)
def ingest(payload: IngestRequest, db: Session = Depends(get_db)):
    try:
        # 1) Find or create the incident
        incident = None
        if payload.incident_id:
            incident = db.get(models.Incident, payload.incident_id)

        if incident is None:
            incident = models.Incident(
                id=payload.incident_id,  # if None, model default will generate uuid
                name=payload.name,
                source=payload.source,
                meta=payload.meta,
            )
            db.add(incident)
            db.flush()  # ensures incident.id is available

        # 2) Insert metric points
        metric_rows = [
            models.MetricPoint(
                incident_id=incident.id,
                ts=m.ts,
                metric_name=m.metric_name,
                value=m.value,
            )
            for m in payload.metrics
        ]

        # 3) Insert events
        event_rows = [
            models.Event(
                incident_id=incident.id,
                ts=e.ts,
                event_type=e.event_type,
                meta=e.meta,
            )
            for e in payload.events
        ]

        # --- bulk insert metrics with ON CONFLICT DO NOTHING ---
        if metric_rows:
            stmt = insert(models.MetricPoint).values([
                {
                    "incident_id": incident.id,
                    "ts": m.ts,
                    "metric_name": m.metric_name,
                    "value": m.value,
                }
                for m in payload.metrics
            ]).on_conflict_do_nothing(
                index_elements=["incident_id", "ts", "metric_name"]
            )
            result_metrics = db.execute(stmt)
            metrics_inserted = result_metrics.rowcount or 0
        else:
            metrics_inserted = 0

        # --- bulk insert events with ON CONFLICT DO NOTHING ---
        if event_rows:
            stmt = insert(models.Event).values([
                {
                    "incident_id": incident.id,
                    "ts": e.ts,
                    "event_type": e.event_type,
                    "meta": e.meta,
                }
                for e in payload.events
            ]).on_conflict_do_nothing(
                index_elements=["incident_id", "ts", "event_type"]
            )
            result_events = db.execute(stmt)
            events_inserted = result_events.rowcount or 0
        else:
            events_inserted = 0

        db.commit()

        return IngestResponse(
            incident_id=incident.id,
            metrics_ingested=metrics_inserted,
            events_ingested=events_inserted,
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analysis/{incident_id}", response_model=AnalysisResponse)
def analyze_incident(incident_id: str, db: Session = Depends(get_db)):
    incident = db.get(models.Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    metric_points = (
        db.query(models.MetricPoint)
        .filter(models.MetricPoint.incident_id == incident_id)
        .order_by(models.MetricPoint.metric_name, models.MetricPoint.ts)
        .all()
    )
    events = (
        db.query(models.Event)
        .filter(models.Event.incident_id == incident_id)
        .order_by(models.Event.ts)
        .all()
    )

    # ---- 1) group points by metric ----
    by_metric = defaultdict(list)
    for mp in metric_points:
        by_metric[mp.metric_name].append(mp)

    # ---- 2) detect point anomalies (z-score vs baseline) ----
    point_anoms: list[AnomalyOut] = []
    z_threshold = 3.0

    for metric_name, pts in by_metric.items():
        if len(pts) < 12:
            continue

        baseline_n = min(30, max(10, len(pts) // 4))
        baseline = pts[:baseline_n]

        mean = sum(p.value for p in baseline) / len(baseline)
        var = sum((p.value - mean) ** 2 for p in baseline) / len(baseline)
        std = math.sqrt(var)
        if std < 1e-9:
            continue

        for p in pts[baseline_n:]:
            z = (p.value - mean) / std
            if abs(z) >= z_threshold:
                point_anoms.append(
                    AnomalyOut(
                        metric_name=metric_name,
                        ts=p.ts,
                        value=p.value,
                        baseline_mean=mean,
                        baseline_std=std,
                        z_score=z,
                    )
                )

    point_anoms.sort(key=lambda a: a.ts)

    # ---- 3) collapse anomalies into "episodes" per metric ----
    # If anomalies are within 2 minutes, treat as one episode.
    episode_gap = timedelta(minutes=2)

    episodes = []  # each: dict(metric, start, end, max_abs_z, mean, std, max_value)
    by_metric_anoms = defaultdict(list)
    for a in point_anoms:
        by_metric_anoms[a.metric_name].append(a)

    for metric_name, anoms in by_metric_anoms.items():
        current = None
        for a in anoms:
            if current is None:
                current = {
                    "metric": metric_name,
                    "start": a.ts,
                    "end": a.ts,
                    "max_abs_z": abs(a.z_score),
                    "baseline_mean": a.baseline_mean,
                    "baseline_std": a.baseline_std,
                    "max_value": a.value,
                }
                continue

            if a.ts - current["end"] <= episode_gap:
                current["end"] = a.ts
                current["max_abs_z"] = max(current["max_abs_z"], abs(a.z_score))
                current["max_value"] = max(current["max_value"], a.value)
            else:
                episodes.append(current)
                current = {
                    "metric": metric_name,
                    "start": a.ts,
                    "end": a.ts,
                    "max_abs_z": abs(a.z_score),
                    "baseline_mean": a.baseline_mean,
                    "baseline_std": a.baseline_std,
                    "max_value": a.value,
                }
        if current is not None:
            episodes.append(current)

    episodes.sort(key=lambda e: e["start"])

    episodes_out: list[EpisodeOut] = []

    for ep in episodes:
        pct = 0.0
        if ep["baseline_mean"] and abs(ep["baseline_mean"]) > 1e-9:
            pct = (ep["max_value"] - ep["baseline_mean"]) / ep["baseline_mean"] * 100.0

        episodes_out.append(
            EpisodeOut(
                metric_name=ep["metric"],  # <-- FIXED comma issue
                start_ts=ep["start"],
                end_ts=ep["end"],
                baseline_mean=ep["baseline_mean"],
                baseline_std=ep["baseline_std"],
                peak_value=ep["max_value"],
                peak_z_score=ep["max_abs_z"],
                percent_change=round(pct, 2),
            )
        )

    # ---- 4) compute multi-metric agreement (episode overlap) ----
    # if latency + error_rate overlap in time, boost.
    def overlaps(a_start, a_end, b_start, b_end) -> bool:
        return not (a_end < b_start or b_end < a_start)

    agreement_bonus = defaultdict(float)  # episode_index -> bonus
    for i, e1 in enumerate(episodes):
        for j, e2 in enumerate(episodes):
            if i >= j:
                continue
            if overlaps(e1["start"], e1["end"], e2["start"], e2["end"]):
                # simple: boost both
                agreement_bonus[i] += 0.35
                agreement_bonus[j] += 0.35

    # ---- 5) link episodes to events & score causes ----
    # event priors (feel free to tweak later)
    event_prior = {
        "deploy": 1.00,
        "config_change": 0.85,
        "feature_flag": 0.75,
        "db_migration": 0.80,
        "incident_note": 0.50,
    }

    window = timedelta(minutes=10)

    # score per event id
    cause = {}  # ev.id -> dict(score, evidence, event)
    max_possible = 0.0

    for idx, ep in enumerate(episodes):
        # severity: cap z so it doesn't explode
        severity = min(10.0, ep["max_abs_z"]) / 10.0  # 0..1
        sev_weight = 0.55 + 0.45 * severity  # 0.55..1.0

        agree = min(0.6, agreement_bonus.get(idx, 0.0))  # 0..0.6
        agree_weight = 1.0 + agree  # 1.0..1.6

        # best matching event(s) in window
        for ev in events:
            dt = abs(ep["start"] - ev.ts)
            if dt <= window:
                proximity = max(0.0, 1.0 - (dt.total_seconds() / window.total_seconds()))  # 0..1
                prior = event_prior.get(ev.event_type, 0.6)  # default mid

                # episode contributes:
                contrib = proximity * prior * sev_weight * agree_weight

                max_possible = max(max_possible, contrib)  # for normalization hint (not strict)

                if ev.id not in cause:
                    cause[ev.id] = {"score": 0.0, "evidence": [], "event": ev}

                cause[ev.id]["score"] += contrib

                pct = 0.0
                if ep["baseline_mean"] > 1e-9:
                    pct = (ep["max_value"] - ep["baseline_mean"]) / ep["baseline_mean"] * 100.0

                cause[ev.id]["evidence"].append(
                    f"{ep['metric']} abnormal {ep['start'].isoformat()}–{ep['end'].isoformat()}: "
                    f"{ep['baseline_mean']:.2f} → {ep['max_value']:.2f} ({pct:+.1f}%), "
                    f"z≈{ep['max_abs_z']:.2f}, event within {int(dt.total_seconds())}s"
                )

    # ---- 6) build response ----
    # return point anomalies (fine for now) + ranked causes
    causes: list[CauseOut] = []
    if cause:
        max_score = max(v["score"] for v in cause.values()) or 1.0
        for v in cause.values():
            ev = v["event"]
            conf = v["score"] / max_score
            causes.append(
                CauseOut(
                    event_type=ev.event_type,
                    ts=ev.ts,
                    meta=ev.meta,
                    confidence=round(conf, 3),
                    evidence=v["evidence"][:6],
                )
            )
        causes.sort(key=lambda c: c.confidence, reverse=True)

    return AnalysisResponse(
        incident_id=incident_id,
        anomalies=point_anoms,
        episodes=episodes_out,  # 👈 this is why we built it
        likely_causes=causes[:5],
    )
