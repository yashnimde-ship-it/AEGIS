import urllib.request
import urllib.error
import json
from aegis._config import get as get_cfg


def _post(url: str, payload: dict) -> None:
    """Blocking POST. Swallows all errors — never let monitoring crash the app."""
    try:
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        # 5s timeout: handles Neon free-tier cold-start latency (~2-5s on first wake)
        urllib.request.urlopen(req, timeout=5.0)
    except Exception:
        pass


def _get_json(url: str) -> dict | None:
    """Blocking GET that returns parsed JSON, or None on any error."""
    try:
        # 5s timeout: same reason as _post; fail-open (return None) on any error
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public helpers called by _trace.py
# ---------------------------------------------------------------------------

def post_event(event: dict) -> None:
    """Send event to backend synchronously — cost commits before next check can read it."""
    cfg = get_cfg()
    if not cfg.initialized:
        return
    _post(f"{cfg.api_url}/events", event)


def check_run_allowed(run_id: str) -> bool:
    """Ask backend if this run is still under budget. Fail-open: True on any error."""
    cfg = get_cfg()
    if not cfg.initialized:
        return True
    result = _get_json(f"{cfg.api_url}/check/{run_id}")
    if result is None:
        return True  # backend unreachable → allow
    return result.get("allowed", True)


def set_agent_budget(agent_name: str, budget: float) -> None:
    """Register agent + budget with backend synchronously so budget is set before first trace."""
    cfg = get_cfg()
    if not cfg.api_url:
        return
    _post(f"{cfg.api_url}/agents/{agent_name}/budget", {"budget_per_run_usd": budget})
