"""One scoring definition, used by the solver model AND by plain-Python scoring of any plan,
so greedy and CP-SAT are always compared on identical terms."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ..constraints.feasibility import Compat, explain_unassigned, validate
from ..domain.models import Aircraft, Assignment, Mission, Plan, State, by_id


@dataclass(frozen=True, slots=True)
class Weights:
    value: int = 10        # scale for mission value (keeps everything integer)
    risk: float = 1.0      # penalty on (1 - p_serviceable) * value for the chosen aircraft
    delay: int = 1         # per slot a sortie starts after its earliest start
    churn: int = 0         # reward per briefed sortie kept exactly as planned


# Operator-facing trade-off presets -> Plan A / B / C.
PRESETS: dict[str, Weights] = {
    "A_max_value": Weights(churn=20, risk=0.5),
    "B_balanced": Weights(churn=120, risk=1.0),
    "C_stable_robust": Weights(churn=600, risk=2.0),
}


def gain(m: Mission, w: Weights) -> int:
    return m.value * w.value


def risk_cost(m: Mission, a: Aircraft, w: Weights) -> int:
    return int(round(w.risk * m.value * (1.0 - a.p_serviceable) * w.value))


def plan_value(plan: Plan, state: State) -> int:
    m_by = by_id(state.missions)
    return sum(m_by[a.mission_id].value for a in plan.assignments if a.mission_id in m_by)


def score_plan(plan: Plan, state: State, w: Weights, reference: Plan | None = None) -> float:
    m_by, a_by = by_id(state.missions), by_id(state.aircraft)
    total = 0.0
    for asg in plan.assignments:
        m, ac = m_by[asg.mission_id], a_by[asg.aircraft_id]
        lo = m.earliest if asg.start < state.now else max(m.earliest, state.now)
        total += gain(m, w) - risk_cost(m, ac, w) - w.delay * (asg.start - lo)
    if reference is not None and w.churn:
        ref = {a.mission_id: (a.aircraft_id, a.crew_id, a.start) for a in reference.assignments}
        total += w.churn * sum(
            1 for a in plan.assignments if ref.get(a.mission_id) == (a.aircraft_id, a.crew_id, a.start))
    return total


def finalize(state: State, assignments: Sequence[Assignment], w: Weights,
             reference: Plan | None, *, status: str, ms: float,
             compat: Compat | None = None, meta: dict[str, Any] | None = None,
             check: bool = True) -> Plan:
    """Turn raw assignments into a fully populated Plan (score, dropped + reasons, validation)."""
    plan = Plan(assignments=sorted(assignments, key=lambda a: (a.start, a.mission_id)),
                status=status, solve_ms=round(ms, 2), meta=meta or {})
    assigned = {a.mission_id for a in plan.assignments}
    plan.dropped = [m.id for m in state.missions if m.id not in assigned]
    if compat is not None:
        plan.reasons = {mid: explain_unassigned(mid, compat) for mid in plan.dropped}
    plan.value = plan_value(plan, state)
    plan.score = score_plan(plan, state, w, reference)
    if check:
        plan.violations = validate(plan, state)
    return plan
