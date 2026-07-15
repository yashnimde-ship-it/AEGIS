import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from datetime import datetime, timezone

from database import engine, get_db, Base
import models
from models import Agent, Event, Alert, RunTotal
from schemas import EventIn, BudgetSet, AgentOut, EventOut, AlertOut, CheckOut, EventAck
from sentinel import get_or_create_agent, upsert_run_total, run_sentinel_checks

# Create all tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AEGIS Sentinel", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this when dashboard has a fixed origin
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# POST /events  — SDK sends one captured LLM call
# ---------------------------------------------------------------------------

@app.post("/events", response_model=EventAck)
def ingest_event(payload: EventIn, db: Session = Depends(get_db)):
    # Ensure agent row exists
    agent = get_or_create_agent(db, payload.agent_name)

    # Store the event
    event = Event(
        agent_name=payload.agent_name,
        run_id=payload.run_id,
        model=payload.model,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        cost_usd=payload.cost_usd,
        latency_ms=payload.latency_ms,
        raw_response=payload.raw_response,
    )
    db.add(event)
    db.commit()

    # Update running total for this run
    run = upsert_run_total(db, payload.run_id, payload.agent_name, payload.cost_usd)

    # Run Sentinel checks (budget + spike)
    run_sentinel_checks(db, run, agent)

    return EventAck(status="ok", run_id=payload.run_id, cost_usd=payload.cost_usd)


# ---------------------------------------------------------------------------
# GET /check/{run_id}  — SDK asks "can I make another call?"
# ---------------------------------------------------------------------------

@app.get("/check/{run_id}", response_model=CheckOut)
def check_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(RunTotal).filter(RunTotal.run_id == run_id).first()
    if not run:
        # First call of a new run — always allowed
        return CheckOut(allowed=True)

    if run.is_over_budget:
        return CheckOut(allowed=False, reason="budget exceeded")

    return CheckOut(allowed=True)


# ---------------------------------------------------------------------------
# POST /agents/{name}/budget  — set or update an agent's budget
# ---------------------------------------------------------------------------

@app.post("/agents/{name}/budget")
def set_budget(name: str, payload: BudgetSet, db: Session = Depends(get_db)):
    agent = get_or_create_agent(db, name)
    agent.budget_per_run_usd = payload.budget_per_run_usd
    db.commit()
    return {"status": "ok", "agent": name, "budget_per_run_usd": payload.budget_per_run_usd}


# ---------------------------------------------------------------------------
# GET /agents  — list all agents with today's stats
# ---------------------------------------------------------------------------

@app.get("/agents", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db)):
    agents = db.query(Agent).all()
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    results = []
    for agent in agents:
        stats = db.query(
            func.coalesce(func.sum(Event.cost_usd), 0),
            func.count(Event.id),
        ).filter(
            Event.agent_name == agent.name,
            Event.created_at >= day_start,
        ).first()

        cost_today = float(stats[0]) if stats else 0.0
        calls_today = int(stats[1]) if stats else 0

        # Alerting = any unresolved P1 today
        is_alerting = db.query(Alert).filter(
            Alert.agent_name == agent.name,
            Alert.severity == "P1",
            Alert.created_at >= day_start,
        ).first() is not None

        results.append(AgentOut(
            name=agent.name,
            budget_per_run_usd=float(agent.budget_per_run_usd),
            cost_today=cost_today,
            calls_today=calls_today,
            is_alerting=is_alerting,
            created_at=agent.created_at,
        ))

    return results


# ---------------------------------------------------------------------------
# GET /agents/{name}/events  — all events for one agent (trace view)
# ---------------------------------------------------------------------------

@app.get("/agents/{name}/events", response_model=list[EventOut])
def agent_events(name: str, limit: int = 200, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.name == name).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    events = (
        db.query(Event)
        .filter(Event.agent_name == name)
        .order_by(Event.created_at.desc())
        .limit(limit)
        .all()
    )
    return events


# ---------------------------------------------------------------------------
# GET /alerts  — recent alerts, newest first
# ---------------------------------------------------------------------------

@app.get("/alerts", response_model=list[AlertOut])
def list_alerts(limit: int = 50, db: Session = Depends(get_db)):
    alerts = (
        db.query(Alert)
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )
    return alerts


# ---------------------------------------------------------------------------
# GET /  — health check
# ---------------------------------------------------------------------------

@app.get("/")
def health():
    return {"status": "ok", "service": "AEGIS Sentinel"}


# ---------------------------------------------------------------------------
# Serve static dashboard — must be mounted AFTER all API routes
# ---------------------------------------------------------------------------

_dashboard_dir = os.path.join(os.path.dirname(__file__), "dashboard")
if not os.path.isdir(_dashboard_dir):
    # Local dev: dashboard/ is a sibling of backend/, not inside it
    _dashboard_dir = os.path.join(os.path.dirname(__file__), "..", "dashboard")
if os.path.isdir(_dashboard_dir):
    app.mount("/dashboard", StaticFiles(directory=_dashboard_dir, html=True), name="dashboard")
