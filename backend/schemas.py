from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field

from engine.domain.enums import EventType

_EVENT_TYPES = {t.value for t in EventType}


def _check_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not events:
        raise ValueError("at least one event is required")
    for e in events:
        missing = {"id", "type", "time"} - set(e)
        if missing:
            raise ValueError(f"event is missing {sorted(missing)}")
        if e["type"] not in _EVENT_TYPES:
            raise ValueError(f"unknown event type {e['type']!r}; use one of {sorted(_EVENT_TYPES)}")
        if not isinstance(e["time"], int) or e["time"] < 0:
            raise ValueError("event time must be a non-negative integer slot")
    return events


Events = Annotated[list[dict[str, Any]], AfterValidator(_check_events)]


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class ScenarioCreateRequest(BaseModel):
    name: str = "Demo Scenario"
    size: str = Field(default="M", pattern="^(S|M|L|XL)$")
    tightness: float = Field(default=0.9, ge=0.5, le=1.2)
    seed: int = 7
    trap_groups: int = Field(default=0, ge=0, le=20)


# ---- scenario-bound requests: the SERVER supplies state/plan from the database -------------
class ScenarioPlanRequest(BaseModel):
    time_limit: float = Field(default=10.0, gt=0, le=120)
    seed: int = 0
    workers: int | None = Field(default=None, ge=1, le=64)


class ScenarioImpactRequest(BaseModel):
    events: Events


class ScenarioReplanRequest(BaseModel):
    events: Events
    time_limit: float = Field(default=5.0, gt=0, le=60)
    seed: int = 0
    robustness_trials: int = Field(default=60, ge=0, le=500)
    workers: int | None = Field(default=None, ge=1, le=64)


# ---- sandbox requests: caller supplies everything; results can NEVER be approved -----------
class PlanRequest(BaseModel):
    state: dict[str, Any]
    time_limit: float = Field(default=10.0, gt=0, le=60)
    seed: int = 0
    workers: int | None = Field(default=None, ge=1, le=64)
    scenario_version_id: str | None = None      # ignored (kept so old clients don't break)


class ImpactRequest(BaseModel):
    state: dict[str, Any]
    plan: dict[str, Any]
    events: Events


class ReplanRequest(BaseModel):
    state: dict[str, Any]
    plan: dict[str, Any]
    events: Events
    time_limit: float = Field(default=5.0, gt=0, le=60)
    seed: int = 0
    robustness_trials: int = Field(default=60, ge=0, le=500)
    include_state: bool = True
    workers: int | None = Field(default=None, ge=1, le=64)
    scenario_version_id: str | None = None      # ignored


class ValidateRequest(BaseModel):
    state: dict[str, Any]
    plan: dict[str, Any]


class StressTestRequest(BaseModel):
    state: dict[str, Any]
    plan: dict[str, Any]
    trials: int = Field(default=200, ge=1, le=2000)
    seed: int = 0


class DecisionRequest(BaseModel):
    """The server takes the plan and state from the stored job result. The client only says
    WHICH job and WHICH option; it can never submit its own plan."""
    scenario_id: str
    action: Literal["approve", "reject", "rollback"]
    job_id: str | None = None                   # required for approve / reject
    option_label: str | None = None             # e.g. "A_max_value" or "greedy_patch"
    rollback_version_id: str | None = None      # required for rollback
    reason: str | None = None


class JobStatusResponse(BaseModel):
    id: str
    type: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    result_ref: str | None = None
    scenario_id: str | None = None
    scenario_version_id: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
