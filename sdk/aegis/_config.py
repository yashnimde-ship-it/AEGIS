from dataclasses import dataclass, field


@dataclass
class _Config:
    agent_name:      str   = ""
    api_url:         str   = ""
    budget_per_run:  float = 5.0
    initialized:     bool  = False


_cfg = _Config()


def init(agent_name: str, api_url: str, budget_per_run: float = 5.0) -> None:
    _cfg.agent_name     = agent_name
    _cfg.api_url        = api_url.rstrip("/")
    _cfg.budget_per_run = budget_per_run
    _cfg.initialized    = True

    # Tell the backend this agent exists with its budget
    from aegis._client import set_agent_budget
    set_agent_budget(agent_name, budget_per_run)


def get() -> _Config:
    return _cfg
