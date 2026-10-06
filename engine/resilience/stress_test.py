"""Monte Carlo robustness: sample aircraft/crew failures from serviceability probabilities,
repair with the fast greedy patcher, and report how much mission value survives.

Fast by construction: only the broken sorties are re-placed (build_compat(only=...)), and
hazards are computed once."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..constraints.feasibility import build_hazards
from ..domain.models import Plan, State, by_id
from ..optimization.baseline import greedy_plan


@dataclass(slots=True)
class StressResult:
    trials: int
    mean_retained: float          # with greedy repair (0..1)
    mean_no_repair: float         # if nobody replans
    p10_retained: float           # bad-day outcome
    worst_retained: float
    mean_affected: float          # sorties broken per trial


def stress_test(state: State, plan: Plan, *, n_trials: int = 100, seed: int = 0,
                crew_fail_p: float = 0.02, repair: bool = True) -> StressResult:
    rng = np.random.default_rng(seed)
    m_by, a_by = by_id(state.missions), by_id(state.aircraft)
    now = state.now
    total = sum(m_by[a.mission_id].value for a in plan.assignments) or 1
    ac_ids = sorted({a.aircraft_id for a in plan.assignments})
    cr_ids = sorted({a.crew_id for a in plan.assignments})
    p_fail_ac = np.array([1.0 - a_by[i].p_serviceable for i in ac_ids])
    hz = build_hazards(state)
    future = [a for a in plan.assignments if a.start >= now]

    kept, plain, affected_n = [], [], []
    for _ in range(n_trials):
        bad_ac = {i for i, f in zip(ac_ids, rng.random(len(ac_ids)) < p_fail_ac) if f}
        bad_cr = {i for i, f in zip(cr_ids, rng.random(len(cr_ids)) < crew_fail_p) if f}
        hit = [a for a in future if a.aircraft_id in bad_ac or a.crew_id in bad_cr]
        lost = sum(m_by[a.mission_id].value for a in hit)
        plain.append((total - lost) / total)
        affected_n.append(len(hit))
        if not hit or not repair:
            kept.append(plain[-1])
            continue
        hit_ids = {a.mission_id for a in hit}
        patch = greedy_plan(state, fixed=[a for a in plan.assignments if a.mission_id not in hit_ids],
                            mission_ids=hit_ids, exclude_aircraft=bad_ac, exclude_crew=bad_cr,
                            hz=hz, check=False)
        regained = sum(m_by[a.mission_id].value for a in patch.assignments if a.mission_id in hit_ids)
        kept.append((total - lost + regained) / total)

    k = np.array(kept)
    return StressResult(n_trials, float(k.mean()), float(np.mean(plain)),
                        float(np.percentile(k, 10)), float(k.min()), float(np.mean(affected_n)))
