# signal

a backend microservice that helps identify **likely root causes of incidents** (e.g. production failures, CI issues) by analyzing time-series metrics and discrete system events.

## features

- 📊 **metric ingestion** – ingest time-series data (latency, error rates, throughput)
- 🔔 **event tracking** – capture discrete changes (deploys, config updates, feature flags)
- 🔍 **anomaly detection** – statistical z-score analysis with adaptive baselines
- 🧩 **episode clustering** – group related anomalies into coherent episodes
- 🎯 **root cause ranking** – correlate anomalies with events using temporal proximity + severity scoring
- 📝 **explainable evidence** – detailed reasoning for each probable cause

built as a production-style api using fastapi, postgresql, and alembic.

---

## how it works

1. **ingest data** → send metrics and events via `POST /ingest`
2. **detect anomalies** → z-score analysis identifies deviations from baseline behavior
3. **cluster episodes** → consecutive anomalies within 2-minute windows are grouped
4. **correlate causes** → events within 10 minutes of episodes are scored by:
   - temporal proximity (closer = higher score)
   - event type priors (deploy > config > flag)
   - anomaly severity (z-score magnitude)
   - multi-metric agreement (overlapping episodes boost confidence)
5. **rank & explain** → return top causes with confidence scores and evidence

---

## api endpoints

### `GET /health`
health check

**response:**
```json
{"status": "ok"}
```

### `POST /ingest`
ingest metrics and events for an incident

**request body:**
```json
{
  "incident_id": "optional-client-id",
  "name": "prod-outage-2026-02-05",
  "source": "prod",
  "meta": {"team": "platform"},
  "metrics": [
    {
      "ts": "2026-02-05T14:30:00Z",
      "metric_name": "p95_latency_ms",
      "value": 1250.5
    }
  ],
  "events": [
    {
      "ts": "2026-02-05T14:28:00Z",
      "event_type": "deploy",
      "meta": {"version": "v2.3.1", "author": "alice"}
    }
  ]
}
```

**response:**
```json
{
  "incident_id": "uuid-generated-or-provided",
  "metrics_ingested": 42,
  "events_ingested": 3
}
```

**notes:**
- idempotent: duplicate (incident_id, ts, metric_name) or (incident_id, ts, event_type) are ignored
- if `incident_id` is omitted, a new uuid is generated

### `GET /analysis/{incident_id}`
analyze an incident and return ranked root causes

**response:**
```json
{
  "incident_id": "uuid",
  "anomalies": [
    {
      "metric_name": "p95_latency_ms",
      "ts": "2026-02-05T14:32:00Z",
      "value": 1850.2,
      "baseline_mean": 250.0,
      "baseline_std": 50.0,
      "z_score": 32.0
    }
  ],
  "episodes": [
    {
      "metric_name": "p95_latency_ms",
      "start_ts": "2026-02-05T14:32:00Z",
      "end_ts": "2026-02-05T14:35:00Z",
      "baseline_mean": 250.0,
      "baseline_std": 50.0,
      "peak_value": 1850.2,
      "peak_z_score": 32.0,
      "percent_change": 640.08
    }
  ],
  "likely_causes": [
    {
      "event_type": "deploy",
      "ts": "2026-02-05T14:28:00Z",
      "meta": {"version": "v2.3.1"},
      "confidence": 0.95,
      "evidence": [
        "p95_latency_ms abnormal 2026-02-05T14:32:00–2026-02-05T14:35:00: 250.00 → 1850.20 (+640.1%), z≈32.00, event within 240s"
      ]
    }
  ]
}
```

---

## tech stack

- **python 3.11+**
- **fastapi** – modern async api framework
- **postgresql** – persistent storage with jsonb support
- **sqlalchemy 2.0** – orm with relationship modeling
- **alembic** – schema migration management
- **pydantic** – request/response validation
- **uvicorn** – asgi server

---

## project structure

```
signal/
├── alembic/                    # database migrations
│   ├── versions/
│   │   └── 9d5e6ee4c19b_create_core_tables.py
│   ├── env.py
│   └── script.py.mako
├── app/
│   ├── db.py                   # database engine + session factory
│   ├── models.py               # sqlalchemy ORM models
│   ├── schemas.py              # pydantic request/response schemas
│   └── main.py                 # fastapi app + endpoints + analysis logic
├── alembic.ini                 # alembic configuration
├── requirements.txt
├── .env                        # DATABASE_URL (not in git)
├── .gitignore
└── README.md
```

---

## setup

### 1. install dependencies

```bash
python3 -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on windows
pip install -r requirements.txt
```

### 2. configure database

create a `.env` file:

```bash
DATABASE_URL=postgresql://user:password@localhost:5432/signal_db
```

### 3. run migrations

```bash
alembic upgrade head
```

### 4. start the server

```bash
uvicorn app.main:app --reload
```

server runs at `http://localhost:8000`

---

## database schema

### `incidents`
| column | type | description |
|--------|------|-------------|
| id | string (uuid) | primary key |
| created_at | timestamp | auto-generated |
| name | string | human-readable identifier |
| source | string | origin (e.g. "prod", "ci") |
| metadata | json | arbitrary key-values |

### `metric_points`
| column | type | description |
|--------|------|-------------|
| id | string (uuid) | primary key |
| incident_id | string | foreign key → incidents |
| ts | timestamp | when the metric was measured |
| metric_name | string | e.g. "p95_latency_ms" |
| value | float | metric value |

**unique constraint:** (incident_id, ts, metric_name)

### `events`
| column | type | description |
|--------|------|-------------|
| id | string (uuid) | primary key |
| incident_id | string | foreign key → incidents |
| ts | timestamp | when the event occurred |
| event_type | string | e.g. "deploy", "config_change" |
| metadata | json | event-specific details |

**unique constraint:** (incident_id, ts, event_type)

---

## analysis algorithm

### 1. anomaly detection
- computes baseline mean/std from first 30 points (or 25% of data)
- flags points with `|z-score| >= 3.0`

### 2. episode clustering
- groups anomalies within 2-minute windows
- tracks peak z-score and max value per episode

### 3. cause scoring
each event is scored based on:
- **temporal proximity**: `1 - (Δt / 10min)` for events within 10-minute window
- **event prior**: deploy=1.0, config=0.85, flag=0.75, migration=0.80, note=0.50
- **severity weight**: `0.55 + 0.45 × min(z/10, 1.0)`
- **agreement bonus**: +0.35 if multiple metrics show overlapping episodes

final confidence is normalized to [0, 1]

### 4. evidence generation
for each cause, we provide:
- metric name
- time range of abnormal behavior
- baseline → peak value (+ percent change)
- z-score magnitude
- time delta to event

---

## example usage

```bash
# ingest data
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "name": "api-slowdown",
    "source": "prod",
    "metrics": [
      {"ts": "2026-02-05T10:00:00Z", "metric_name": "latency", "value": 120},
      {"ts": "2026-02-05T10:01:00Z", "metric_name": "latency", "value": 950}
    ],
    "events": [
      {"ts": "2026-02-05T09:59:00Z", "event_type": "deploy", "meta": {"version": "v1.2.3"}}
    ]
  }'

# analyze
curl http://localhost:8000/analysis/{incident_id}
```

---

## future improvements

- [ ] machine learning models for anomaly detection (LSTM, Prophet)
- [ ] bayesian inference for cause likelihood
- [ ] seasonality-aware baselines
- [ ] dependency graph analysis
- [ ] real-time streaming ingestion (kafka/rabbitmq)
- [ ] grafana/datadog integration
- [ ] alert routing based on confidence thresholds

---

## license

mit license - see [LICENSE](LICENSE)
