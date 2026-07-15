from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


# --- Inbound from SDK ---

class EventIn(BaseModel):
    agent_name:    str
    run_id:        str
    model:         str
    input_tokens:  int
    output_tokens: int
    cost_usd:      float
    latency_ms:    int
    raw_response:  Optional[Any] = None


class BudgetSet(BaseModel):
    budget_per_run_usd: float


# --- Outbound to dashboard ---

class AgentOut(BaseModel):
    name:               str
    budget_per_run_usd: float
    cost_today:         float
    calls_today:        int
    is_alerting:        bool
    created_at:         datetime

    class Config:
        from_attributes = True


class EventOut(BaseModel):
    id:            int
    agent_name:    str
    run_id:        str
    model:         str
    input_tokens:  int
    output_tokens: int
    cost_usd:      float
    latency_ms:    int
    created_at:    datetime

    class Config:
        from_attributes = True


class AlertOut(BaseModel):
    id:             int
    agent_name:     str
    run_id:         Optional[str]
    alert_type:     str
    severity:       str
    message:        str
    current_value:  Optional[float]
    baseline_value: Optional[float]
    created_at:     datetime

    class Config:
        from_attributes = True


class CheckOut(BaseModel):
    allowed: bool
    reason:  Optional[str] = None


class EventAck(BaseModel):
    status:  str
    run_id:  str
    cost_usd: float
