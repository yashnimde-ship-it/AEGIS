from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import func, text

from models import Agent, Alert, RunTotal, Event


# ---------------------------------------------------------------------------
# Atlas import — project root is added to sys.path by main.py at startup
# ---------------------------------------------------------------------------

def _try_import_atlas():
    try:
        from atlas.atlas import explain_alert
        return explain_alert
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _events_for_run(db: Session, run_id: str) -> list[dict]:
    rows = (
        db.query(Event)
        .filter(Event.run_id == run_id)
        .order_by(Event.created_at.desc())
        .limit(10)
        .all()
    )
    return [{"model": e.model, "cost_usd": float(e.cost_usd), "call_count": 1} for e in rows]


def _events_for_agent_hour(db: Session, agent_name: str) -> list[dict]:
    hour_start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    rows = (
        db.query(Event)
        .filter(Event.agent_name == agent_name, Event.created_at >= hour_start)
        .order_by(Event.created_at.desc())
        .limit(10)
        .all()
    )
    return [{"model": e.model, "cost_usd": float(e.cost_usd), "call_count": 1} for e in rows]


def _enrich_with_atlas(db: Session, alert: Alert, recent_events: list[dict]) -> None:
    """
    Call Atlas to populate explanation fields on the alert.
    Fail-silent: any exception is swallowed — Atlas must never crash Sentinel.

    NOTE: This adds ~1s latency to /events when an alert fires (Groq call).
    The circuit-breaker flag (is_over_budget) is committed BEFORE this runs,
    so /check is never affected by Atlas latency.
    """
    explain_alert = _try_import_atlas()
    if explain_alert is None:
        return
    try:
        result = explain_alert(
            {
                "alert_type": alert.alert_type,
                "agent_name": alert.agent_name,
                "severity": alert.severity,
                "message": alert.message,
                "current_value": float(alert.current_value or 0),
                "baseline_value": float(alert.baseline_value or 0),
            },
            recent_events,
        )
        alert.atlas_explanation = result.get("explanation")
        alert.atlas_suggested_fix = result.get("suggested_fix")
        alert.atlas_matched_id = result.get("matched_incident_id")
        alert.atlas_confidence = result.get("confidence")
        db.commit()
    except Exception:
        pass  # second safety net — Atlas failure must never crash Sentinel


# ---------------------------------------------------------------------------
# Core sentinel logic (unchanged public interface)
# ---------------------------------------------------------------------------

def get_or_create_agent(db: Session, name: str) -> Agent:
    agent = db.query(Agent).filter(Agent.name == name).first()
    if not agent:
        agent = Agent(name=name)
        db.add(agent)
        db.commit()
        db.refresh(agent)
    return agent


def upsert_run_total(db: Session, run_id: str, agent_name: str, cost: float) -> RunTotal:
    run = db.query(RunTotal).filter(RunTotal.run_id == run_id).first()
    if run:
        run.total_cost_usd = float(run.total_cost_usd) + cost
        run.call_count += 1
    else:
        run = RunTotal(
            run_id=run_id,
            agent_name=agent_name,
            total_cost_usd=cost,
            call_count=1,
        )
        db.add(run)
    db.commit()
    db.refresh(run)
    return run


def check_budget(db: Session, run: RunTotal, agent: Agent) -> bool:
    """Returns True if budget is now exceeded (newly crossed). Marks run as over budget."""
    if run.is_over_budget:
        return False  # already flagged

    budget = float(agent.budget_per_run_usd)
    if float(run.total_cost_usd) > budget:
        run.is_over_budget = True
        db.commit()  # commit circuit-breaker flag BEFORE Atlas runs

        alert = Alert(
            agent_name=agent.name,
            run_id=run.run_id,
            alert_type="budget_exceeded",
            severity="P1",
            message=(
                f"{agent.name} exceeded ${budget:.4f} budget — "
                f"run halted at ${float(run.total_cost_usd):.4f} "
                f"after {run.call_count} calls."
            ),
            current_value=run.total_cost_usd,
            baseline_value=agent.budget_per_run_usd,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        recent = _events_for_run(db, run.run_id)
        _enrich_with_atlas(db, alert, recent)
        return True
    return False


def check_spike(db: Session, agent: Agent):
    """Compares current hour cost vs 24h average. Fires P2 alert if > spike_multiplier×."""
    now = datetime.now(timezone.utc)
    hour_start = now.replace(minute=0, second=0, microsecond=0)

    current_hour_cost = db.query(func.coalesce(func.sum(Event.cost_usd), 0)).filter(
        Event.agent_name == agent.name,
        Event.created_at >= hour_start,
    ).scalar() or 0.0

    rows = db.execute(
        text("""
            SELECT COALESCE(SUM(cost_usd), 0) AS hourly
            FROM events
            WHERE agent_name = :name
              AND created_at >= now() - interval '24 hours'
              AND created_at <  date_trunc('hour', now())
            GROUP BY date_trunc('hour', created_at)
        """),
        {"name": agent.name},
    ).fetchall()

    if not rows:
        return  # not enough history to compare

    avg_hourly = sum(float(r[0]) for r in rows) / len(rows)
    multiplier = float(agent.spike_multiplier)

    if avg_hourly > 0 and float(current_hour_cost) > avg_hourly * multiplier:
        alert = Alert(
            agent_name=agent.name,
            run_id=None,
            alert_type="cost_spike",
            severity="P2",
            message=(
                f"{agent.name} cost spike detected — "
                f"${float(current_hour_cost):.4f} this hour vs "
                f"${avg_hourly:.4f} avg ({multiplier}× threshold)."
            ),
            current_value=current_hour_cost,
            baseline_value=avg_hourly,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        recent = _events_for_agent_hour(db, agent.name)
        _enrich_with_atlas(db, alert, recent)


def run_sentinel_checks(db: Session, run: RunTotal, agent: Agent):
    check_budget(db, run, agent)
    check_spike(db, agent)
