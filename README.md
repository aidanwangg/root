# root

a backend microservice that helps identify **likely root causes of incidents** (e.g. production failures, CI issues) by analyzing time-series metrics and discrete system events.

features:
- ingests metrics and events
- detects anomalous behavior
- links anomalies to nearby changes (deploys, flags, config updates)
- ranks likely causes with explainable evidence

built as a production-style api using fastapi, postgresql, and alembic.

---

## current status

✅ fastapi application scaffolded  
✅ postgresql database configured  
✅ sqlalchemy ORM models defined  
✅ alembic migrations set up and applied  

**next steps**
- define api schemas
- implement `POST /ingest`
- implement `GET /analysis/{incident_id}`
- add anomaly detection + scoring logic

---

## tech stack

- **python 3**
- **fastapi** – api framework
- **postgresql** – persistent storage
- **sqlalchemy** – ORM
- **alembic** – schema migrations
- **pydantic** – request/response validation

---

## project structure

tba
