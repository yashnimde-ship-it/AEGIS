from sqlalchemy import (
    Column, Text, Integer, Numeric, Boolean, BigInteger,
    DateTime, ForeignKey, func, JSON
)
from sqlalchemy.dialects.postgresql import JSONB
from database import Base
import uuid


def _uuid():
    return str(uuid.uuid4())


class Agent(Base):
    __tablename__ = "agents"

    name               = Column(Text, primary_key=True)
    budget_per_run_usd = Column(Numeric(10, 4), default=5.0)
    spike_multiplier   = Column(Numeric(4, 2), default=3.0)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = "events"

    id            = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    agent_name    = Column(Text, ForeignKey("agents.name"), nullable=False)
    run_id        = Column(Text, nullable=False)
    model         = Column(Text, nullable=False)
    input_tokens  = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cost_usd      = Column(Numeric(10, 6), nullable=False, default=0)
    latency_ms    = Column(Integer, nullable=False, default=0)
    raw_response  = Column(JSON().with_variant(JSONB, "postgresql"))
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id             = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    agent_name     = Column(Text, ForeignKey("agents.name"), nullable=False)
    run_id         = Column(Text, nullable=True)
    alert_type     = Column(Text, nullable=False)   # 'budget_exceeded' | 'cost_spike'
    severity       = Column(Text, nullable=False, default="P2")
    message        = Column(Text, nullable=False)
    current_value  = Column(Numeric(12, 6))
    baseline_value = Column(Numeric(12, 6))
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    # Atlas engine output — populated asynchronously after alert creation
    atlas_explanation  = Column(Text, nullable=True)
    atlas_suggested_fix = Column(Text, nullable=True)
    atlas_matched_id   = Column(Text, nullable=True)
    atlas_confidence   = Column(Text, nullable=True)


class RunTotal(Base):
    __tablename__ = "run_totals"

    run_id         = Column(Text, primary_key=True)
    agent_name     = Column(Text, ForeignKey("agents.name"), nullable=False)
    total_cost_usd = Column(Numeric(12, 6), nullable=False, default=0)
    call_count     = Column(Integer, nullable=False, default=0)
    is_over_budget = Column(Boolean, nullable=False, default=False)
    started_at     = Column(DateTime(timezone=True), server_default=func.now())
