from sqlalchemy.orm import Session
from sqlalchemy import func, text
from datetime import datetime, timezone
from models import Agent, Alert, RunTotal, Event


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
        db.commit()

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

    # Average hourly cost over the previous 24h (excluding the current hour)
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


def run_sentinel_checks(db: Session, run: RunTotal, agent: Agent):
    check_budget(db, run, agent)
    check_spike(db, agent)
