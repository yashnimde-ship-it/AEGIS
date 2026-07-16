"""
Atlas engine — "why did it fail" intelligence layer for AEGIS Sentinel.

Triggered by Sentinel alerts (budget_exceeded, cost_spike). Matches against the
curated incident corpus and asks Groq to reason over the matches. Fail-silent:
any error returns a fallback dict; never raises.

Config (all via environment):
  GROQ_API_KEY   — required; if absent, always returns fallback
  GROQ_BASE_URL  — defaults to https://api.groq.com/openai/v1
  ATLAS_MODEL    — defaults to llama-3.3-70b-versatile
"""

import json
import os
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Corpus — loaded once at import time, never re-read
# ---------------------------------------------------------------------------

_CORPUS: list[dict] = json.loads((Path(__file__).parent / "incidents.json").read_text())

# ---------------------------------------------------------------------------
# Category mapping: which incident categories are semantically relevant for
# each alert_type Sentinel can fire.
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[str, list[str]] = {
    "budget_exceeded": [
        "budget_exceeded",
        "retry_loop",
        "infinite_loop",
        "token_bloat",
        "cost_spike",
    ],
    "cost_spike": [
        "cost_spike",
        "token_bloat",
        "retry_loop",
        "infinite_loop",
        "rate_limit",
        "budget_exceeded",
    ],
}


# ---------------------------------------------------------------------------
# Candidate selection — rule-based, no embeddings
# ---------------------------------------------------------------------------

def _select_candidates(alert_type: str, recent_events: list[dict]) -> list[dict]:
    relevant = _CATEGORY_MAP.get(alert_type, [alert_type])

    # Pull tokens from event context for keyword scoring
    keywords: set[str] = set()
    for ev in recent_events:
        model = ev.get("model", "")
        keywords.update(w for w in re.split(r"[-_/]", model.lower()) if len(w) > 2)

    scored: list[tuple[int, int, dict]] = []
    for inc in _CORPUS:
        if inc["category"] not in relevant:
            continue
        cat_rank = relevant.index(inc["category"])
        text = (inc["symptom"] + " " + inc["likely_cause"]).lower()
        kw_hits = sum(1 for kw in keywords if kw in text)
        scored.append((cat_rank, -kw_hits, inc))

    scored.sort(key=lambda t: (t[0], t[1]))
    return [inc for _, _, inc in scored[:5]]


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(alert: dict, recent_events: list[dict], candidates: list[dict]) -> str:
    event_lines = "\n".join(
        f"  - model={ev.get('model', '?')}, cost=${ev.get('cost_usd', 0):.6f}"
        for ev in recent_events
    ) or "  (no recent events provided)"

    patterns = ""
    for i, inc in enumerate(candidates, 1):
        patterns += (
            f"\nPattern {i} [id: {inc['id']}]\n"
            f"Symptom: {inc['symptom']}\n"
            f"Likely cause: {inc['likely_cause']}\n"
            f"Typical fix: {inc['typical_fix']}\n"
        )

    return f"""You are AEGIS Atlas, an AI agent cost-monitoring assistant.
An alert fired in AEGIS Sentinel. Your job is to identify the most likely root cause.

ALERT:
- Type: {alert.get('alert_type')}
- Agent: {alert.get('agent_name')}
- Severity: {alert.get('severity')}
- Message: {alert.get('message')}
- Current value: ${float(alert.get('current_value') or 0):.6f}
- Budget / baseline: ${float(alert.get('baseline_value') or 0):.6f}

RECENT EVENTS (last calls for this agent/run):
{event_lines}

CANDIDATE INCIDENT PATTERNS FROM THE KNOWLEDGE BASE:
{patterns}
INSTRUCTIONS:
1. Select which pattern best fits by its id, or use "no_match" if none fits.
2. Write a 2-3 sentence explanation grounded ONLY in the provided patterns and
   the telemetry above. Do not invent causes that are not in the patterns.
3. State the typical fix verbatim from the matched pattern (or null if no_match).
4. Rate confidence: "high" (symptom closely matches), "medium" (partial),
   or "low" (weak match or no_match).

Respond with ONLY valid JSON, no markdown fences, no extra text:
{{
  "matched_incident_id": "<id or no_match>",
  "explanation": "<2-3 sentences>",
  "suggested_fix": "<fix text or null>",
  "confidence": "<high|medium|low>"
}}"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def explain_alert(alert: dict, recent_events: list[dict]) -> dict:
    """
    Match alert against corpus, call Groq, return structured explanation.
    NEVER raises — returns fallback dict on any failure.
    """
    fallback = {
        "matched_incident_id": None,
        "explanation": "Atlas unavailable — explanation could not be generated.",
        "suggested_fix": None,
        "confidence": "low",
    }

    try:
        from openai import OpenAI  # lazy import; openai may not be installed in all envs

        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            return fallback

        base_url = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        model = os.environ.get("ATLAS_MODEL", "llama-3.3-70b-versatile")

        candidates = _select_candidates(alert.get("alert_type", ""), recent_events)
        if not candidates:
            return fallback

        prompt = _build_prompt(alert, recent_events, candidates)

        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
            timeout=10.0,  # never block Sentinel's event path for more than 10s
        )

        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if the model wraps output despite instructions
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if fence_match:
            raw = fence_match.group(1)

        result: dict = json.loads(raw)

        confidence = result.get("confidence", "low")
        if confidence not in ("high", "medium", "low"):
            confidence = "low"

        matched_id = result.get("matched_incident_id") or None
        if matched_id == "no_match":
            matched_id = None

        return {
            "matched_incident_id": matched_id,
            "explanation": str(result.get("explanation", ""))[:2000],
            "suggested_fix": str(result.get("suggested_fix") or "")[:1000] or None,
            "confidence": confidence,
        }

    except Exception:
        return fallback
