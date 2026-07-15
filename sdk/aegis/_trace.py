import time
import uuid
import functools
from contextvars import ContextVar

from aegis._config import get as get_cfg
from aegis._client import post_event, check_run_allowed
from aegis.prices import calculate_cost

# Holds the run_id for the current call chain.
# Nested @trace calls inherit this instead of starting a new run.
_current_run_id: ContextVar[str | None] = ContextVar("_current_run_id", default=None)


class AegisBudgetError(Exception):
    """Raised when a run has exceeded its budget and the call is blocked."""


def _extract_usage(response) -> tuple[str, int, int]:
    """
    Pull model name + token counts out of an OpenAI or Anthropic response object.
    Returns (model, input_tokens, output_tokens).
    """
    model = getattr(response, "model", "unknown")

    usage = getattr(response, "usage", None)
    if usage is None:
        return model, 0, 0

    # OpenAI: prompt_tokens / completion_tokens
    if hasattr(usage, "prompt_tokens"):
        return model, getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0)

    # Anthropic: input_tokens / output_tokens
    if hasattr(usage, "input_tokens"):
        return model, getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0)

    return model, 0, 0


def _safe_serialize(response) -> dict | None:
    """Best-effort conversion of response object to a plain dict for storage."""
    try:
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "to_dict"):
            return response.to_dict()
        return None
    except Exception:
        return None


def trace(fn):
    """
    Decorator that captures every LLM API call and reports it to the AEGIS backend.

    Usage:
        @aegis.trace
        def ask_llm(prompt):
            return openai.chat.completions.create(...)
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        cfg = get_cfg()

        # --- Determine run_id (inherit from parent or start a new run) ---
        is_root_call = _current_run_id.get() is None
        if is_root_call:
            run_id = str(uuid.uuid4())
            token  = _current_run_id.set(run_id)
        else:
            run_id = _current_run_id.get()
            token  = None

        # --- Circuit-breaker check BEFORE the real call ---
        if cfg.initialized:
            allowed = check_run_allowed(run_id)
            if not allowed:
                if token:
                    _current_run_id.reset(token)
                raise AegisBudgetError(
                    f"Run {run_id} has exceeded its budget. "
                    "Catch aegis.AegisBudgetError to handle this gracefully."
                )

        # --- Make the real call ---
        start_ms = time.monotonic()
        try:
            response = fn(*args, **kwargs)
        finally:
            if token:
                _current_run_id.reset(token)

        latency_ms = int((time.monotonic() - start_ms) * 1000)

        # --- Read usage and calculate cost ---
        model, input_tokens, output_tokens = _extract_usage(response)

        # Outer task-wrapper functions return no LLM usage — skip junk $0 "unknown" rows
        if model == "unknown" and input_tokens == 0 and output_tokens == 0:
            return response

        cost_usd = calculate_cost(model, input_tokens, output_tokens)

        # --- Build event and send synchronously (ensures cost commits before next check) ---
        event = {
            "agent_name":    cfg.agent_name if cfg.initialized else "unknown",
            "run_id":        run_id,
            "model":         model,
            "input_tokens":  input_tokens,
            "output_tokens": output_tokens,
            "cost_usd":      cost_usd,
            "latency_ms":    latency_ms,
            "raw_response":  _safe_serialize(response),
        }

        if cfg.initialized:
            post_event(event)

        return response

    return wrapper
