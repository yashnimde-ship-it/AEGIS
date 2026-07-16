"""
Helm — AEGIS cost intelligence engine.
Rules-based, deterministic SQL aggregation. No LLM, no external APIs.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── Part 2: Illustrative cloud-infra cost ─────────────────────────────────
# CRITICAL: all figures carry illustrative=True and a label string.
# The dashboard renders a visible "Illustrative" badge on this section.

_CLOUD_INFRA_COST = {
    "illustrative": True,
    "label": "Illustrative — representative production-scale estimate. Not real billing data.",
    "monthly_usd": {
        "compute":    {"service": "AWS App Runner", "cost_usd": 45.00, "note": "~2 vCPU, 4 GB, 500 req/min"},
        "database":   {"service": "Neon Postgres",  "cost_usd": 19.00, "note": "Launch plan, 10 GB storage"},
        "storage":    {"service": "AWS S3",          "cost_usd":  2.50, "note": "50 GB + 10K requests/month"},
        "networking": {"service": "Data Transfer",   "cost_usd":  8.00, "note": "~80 GB outbound/month"},
    },
    "total_monthly_usd": 74.50,
}


# ── Part 4: Static recommendation map ─────────────────────────────────────
# Looked up by problem-type key — deterministic, never generated.

_RECOMMENDATION_MAP: dict[str, dict] = {
    "budget_exceeded": {
        "issue":          "Per-run budget exceeded — agent hit spend cap",
        "recommendation": (
            "Enforce a max step count per run. The AEGIS circuit breaker already halts calls "
            "once the cap is crossed — ensure every agent calls aegis.init() with budget_per_run set."
        ),
        "est_impact": "Prevents unbounded spend; direct run-level cap.",
    },
    "cost_spike": {
        "issue":          "Hourly cost spike (>3× baseline)",
        "recommendation": (
            "Add exponential backoff + a hard retry cap (≤ 3 retries). "
            "Repeated identical calls or retry loops are the most common spike driver."
        ),
        "est_impact": "Eliminates retry-loop waste; typically 40–70% spike reduction.",
    },
    "high_avg_cost": {
        "issue":          "High average cost per call",
        "recommendation": (
            "Route simple/low-risk calls to a cheaper model (gpt-4o-mini or Claude Haiku) — "
            "can cut cost ~90% per call."
        ),
        "est_impact": "Up to 90% cost reduction on routable calls.",
    },
    "token_bloat": {
        "issue":          "High token usage per call",
        "recommendation": (
            "Trim conversation history; summarise instead of appending raw history. "
            "Truncate context to the top-k most relevant chunks."
        ),
        "est_impact": "Typically 30–60% token reduction.",
    },
    "context_overflow": {
        "issue":          "Context overflow / very large prompts",
        "recommendation": (
            "Chunk documents and retrieve only top-k relevant context "
            "instead of passing full documents."
        ),
        "est_impact": "Reduces per-call token cost and avoids truncation errors.",
    },
    "unbounded_loop": {
        "issue":          "Unbounded agent loop — run halted by circuit breaker",
        "recommendation": (
            "Add a max_iterations guard in your agent loop. "
            "Log and surface the iteration count so runaway loops are visible early."
        ),
        "est_impact": "Stops runaway agents before costs compound.",
    },
}


def get_costs(db: "Session") -> dict:
    """
    Entry point for GET /helm/costs.
    Returns all five parts: real AI analytics, illustrative cloud cost,
    alert tracking, recommendations, and cost leaks.
    Never raises — returns partial/empty data on DB error.
    """
    try:
        from sqlalchemy import text

        # ── Part 1: Real AI cost analytics ──────────────────────────────

        row_all = db.execute(
            text("SELECT COALESCE(SUM(cost_usd), 0), COUNT(*) FROM events")
        ).fetchone()
        total_spend_all = float(row_all[0]) if row_all else 0.0
        total_calls_all = int(row_all[1]) if row_all else 0

        row_today = db.execute(
            text(
                "SELECT COALESCE(SUM(cost_usd), 0), COUNT(*) FROM events "
                "WHERE created_at >= date_trunc('day', now() AT TIME ZONE 'UTC')"
            )
        ).fetchone()
        total_spend_today = float(row_today[0]) if row_today else 0.0
        total_calls_today = int(row_today[1]) if row_today else 0

        total_spend = {
            "all_time_usd": round(total_spend_all, 6),
            "today_usd":    round(total_spend_today, 6),
            "total_calls":  total_calls_all,
            "calls_today":  total_calls_today,
        }

        # By agent — sorted desc by total cost
        agent_rows = db.execute(
            text(
                "SELECT agent_name, SUM(cost_usd), COUNT(*) "
                "FROM events GROUP BY agent_name ORDER BY SUM(cost_usd) DESC"
            )
        ).fetchall()
        by_agent = [
            {
                "agent_name":        r[0],
                "total_cost_usd":    round(float(r[1]), 6),
                "call_count":        int(r[2]),
                "avg_cost_per_call": round(float(r[1]) / int(r[2]), 6) if r[2] else 0.0,
            }
            for r in agent_rows
        ]

        # By model — sorted desc, with share_percent of total spend
        model_rows = db.execute(
            text(
                "SELECT model, SUM(cost_usd), COUNT(*) "
                "FROM events GROUP BY model ORDER BY SUM(cost_usd) DESC"
            )
        ).fetchall()
        safe_total = total_spend_all or 1.0
        by_model = [
            {
                "model":          r[0],
                "total_cost_usd": round(float(r[1]), 6),
                "call_count":     int(r[2]),
                "share_percent":  round(float(r[1]) / safe_total * 100, 1),
            }
            for r in model_rows
        ]

        # Spend over time — hourly buckets, UTC
        time_rows = db.execute(
            text(
                "SELECT date_trunc('hour', created_at AT TIME ZONE 'UTC') AS hr, "
                "SUM(cost_usd) "
                "FROM events GROUP BY hr ORDER BY hr ASC"
            )
        ).fetchall()
        spend_over_time = [
            {
                "hour":           r[0].isoformat() if r[0] else None,
                "total_cost_usd": round(float(r[1]), 6),
            }
            for r in time_rows
        ]

        # ── Part 3: Cost-alert tracking ──────────────────────────────────
        # For each cost alert, correlate to the driving agent + top model.

        alert_rows = db.execute(
            text(
                "SELECT id, agent_name, alert_type, current_value, run_id, created_at "
                "FROM alerts "
                "WHERE alert_type IN ('budget_exceeded', 'cost_spike') "
                "ORDER BY created_at DESC LIMIT 20"
            )
        ).fetchall()

        cost_alerts = []
        for alert_id, agent_name, alert_type, cost_at_alert, run_id, created_at in alert_rows:
            if run_id:
                # Budget exceeded: look at events for this specific run
                top_row = db.execute(
                    text(
                        "SELECT model, SUM(cost_usd) "
                        "FROM events WHERE run_id = :run_id "
                        "GROUP BY model ORDER BY SUM(cost_usd) DESC LIMIT 1"
                    ),
                    {"run_id": run_id},
                ).fetchone()
            else:
                # Cost spike: look at the agent's events in the hour before the alert
                top_row = db.execute(
                    text(
                        "SELECT model, SUM(cost_usd) "
                        "FROM events WHERE agent_name = :name "
                        "AND created_at >= :ts - interval '1 hour' "
                        "GROUP BY model ORDER BY SUM(cost_usd) DESC LIMIT 1"
                    ),
                    {"name": agent_name, "ts": created_at},
                ).fetchone()

            top_model      = top_row[0] if top_row else "unknown"
            top_model_cost = round(float(top_row[1]), 6) if top_row else 0.0
            driver_summary = (
                f"Top driver: {top_model} (${top_model_cost:.4f})"
                if top_model != "unknown"
                else "Model breakdown unavailable"
            )

            cost_alerts.append({
                "alert_id":      alert_id,
                "agent_name":    agent_name,
                "alert_type":    alert_type,
                "cost_at_alert": round(float(cost_at_alert or 0), 6),
                "top_model":     top_model,
                "driver_summary": driver_summary,
                "fired_at":      created_at.isoformat() if created_at else None,
            })

        # ── Part 5: Cost leaks ───────────────────────────────────────────
        # Agents with avg_cost_per_call > 2× fleet mean, OR that triggered alerts.

        alerted_names = {ca["agent_name"] for ca in cost_alerts}
        fleet_avg = (
            sum(a["avg_cost_per_call"] for a in by_agent) / len(by_agent)
            if by_agent else 0.0
        )

        cost_leaks = []
        for ag in by_agent:
            reasons = []
            if fleet_avg > 0 and ag["avg_cost_per_call"] > fleet_avg * 2:
                reasons.append(
                    f"avg ${ag['avg_cost_per_call']:.6f}/call > 2× fleet mean (${fleet_avg:.6f})"
                )
            if ag["agent_name"] in alerted_names:
                reasons.append("triggered cost alert")
            if reasons:
                cost_leaks.append({
                    "agent_name":        ag["agent_name"],
                    "reason":            "; ".join(reasons),
                    "avg_cost_per_call": ag["avg_cost_per_call"],
                })

        # ── Part 4: Recommendations — from static map only ───────────────
        # One recommendation per detected problem type, looked up by key.

        recommendations = []
        seen: set[str] = set()

        for ca in cost_alerts:
            key = ca["alert_type"]
            if key in _RECOMMENDATION_MAP and key not in seen:
                rec = dict(_RECOMMENDATION_MAP[key])
                rec["agent_name"] = ca["agent_name"]
                recommendations.append(rec)
                seen.add(key)

        for leak in cost_leaks:
            if "fleet mean" in leak["reason"] and "high_avg_cost" not in seen:
                rec = dict(_RECOMMENDATION_MAP["high_avg_cost"])
                rec["agent_name"] = leak["agent_name"]
                recommendations.append(rec)
                seen.add("high_avg_cost")

        return {
            "total_spend":     total_spend,
            "by_agent":        by_agent,
            "by_model":        by_model,
            "spend_over_time": spend_over_time,
            "cloud_infra_cost": _CLOUD_INFRA_COST,
            "cost_alerts":     cost_alerts,
            "cost_leaks":      cost_leaks,
            "recommendations": recommendations,
        }

    except Exception as exc:
        return {
            "error":           str(exc),
            "total_spend":     {"all_time_usd": 0, "today_usd": 0, "total_calls": 0, "calls_today": 0},
            "by_agent":        [],
            "by_model":        [],
            "spend_over_time": [],
            "cloud_infra_cost": _CLOUD_INFRA_COST,
            "cost_alerts":     [],
            "cost_leaks":      [],
            "recommendations": [],
        }
