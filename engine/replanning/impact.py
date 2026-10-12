"""Impact analysis: which sorties does an event break, and what ripples from them?"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..constraints.feasibility import validate
from ..domain.models import Assignment, Plan, PlanMetrics, State, Violation, by_id


@dataclass(slots=True)
class Impact:
    directly_affected: list[str]
    ripple: list[str]                       # same aircraft/crew, later in time, not broken themselves
    reasons: dict[str, list[str]]
    resources: dict[str, list[str]]
    value_at_risk: int
    violations: list[Violation]


def analyze_impact(new_state: State, plan: Plan) -> Impact:
    """Validate the existing plan against the post-event state. Whatever now violates a
    rule (for sorties that have not started) is directly affected."""
    viol = validate(plan, new_state)
    reasons: dict[str, list[str]] = defaultdict(list)
    for v in viol:
        if v.mission_id:
            reasons[v.mission_id].append(v.kind)
    direct = set(reasons)
    m_by = by_id(new_state.missions)
    by_mission = {a.mission_id: a for a in plan.assignments}

    hit_ac: dict[str, int] = {}
    hit_cr: dict[str, int] = {}
    for mid in direct:
        a = by_mission[mid]
        hit_ac[a.aircraft_id] = min(hit_ac.get(a.aircraft_id, 10**9), a.start)
        hit_cr[a.crew_id] = min(hit_cr.get(a.crew_id, 10**9), a.start)
    ripple = sorted(
        a.mission_id for a in plan.assignments
        if a.mission_id not in direct and a.start >= new_state.now
        and (a.start >= hit_ac.get(a.aircraft_id, 10**9) or a.start >= hit_cr.get(a.crew_id, 10**9)))

    bases = {x.id: x.base_id for x in new_state.aircraft}
    return Impact(
        directly_affected=sorted(direct), ripple=ripple, reasons=dict(reasons),
        resources={"aircraft": sorted(hit_ac), "crew": sorted(hit_cr),
                   "bases": sorted({bases[by_mission[m].aircraft_id] for m in direct})},
        value_at_risk=sum(m_by[m].value for m in direct), violations=viol)


def diff_plans(old: Plan, new: Plan, since: int = 0) -> dict[str, list[str]]:
    o = {a.mission_id: a for a in old.assignments if a.start >= since}
    n = {a.mission_id: a for a in new.assignments}
    key = lambda a: (a.aircraft_id, a.crew_id, a.start)
    return {
        "changed": [m for m, a in o.items() if m in n and key(a) != key(n[m])],
        "dropped": [m for m in o if m not in n],
        "added": [m for m in n if m not in {a.mission_id for a in old.assignments}],
    }


def compute_metrics(new_plan: Plan, old_plan: Plan, state: State, *, original_value: int,
                    solve_ms: float | None = None, robustness: float | None = None) -> PlanMetrics:
    """`state` is the post-event state (state.now = event time). Only sorties that had not
    started count towards churn."""
    d = diff_plans(old_plan, new_plan, since=state.now)
    future_old = sum(1 for a in old_plan.assignments if a.start >= state.now)
    changed = len(d["changed"]) + len(d["dropped"])
    return PlanMetrics(
        value=new_plan.value, value_retained=new_plan.value / max(1, original_value),
        missions=len(new_plan.assignments), sorties_changed=changed,
        stability=1.0 - changed / max(1, future_old),
        solve_ms=new_plan.solve_ms if solve_ms is None else solve_ms,
        violations=len(validate(new_plan, state)), robustness=robustness)
