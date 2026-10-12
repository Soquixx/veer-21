"""Minimal-disruption replanning.

1. apply the event(s)            2. find what broke (and what ripples)
3. lock what must not move: sorties already started or inside the freeze window
4. re-optimise the rest with a churn reward so briefed sorties stay put unless moving pays off
5. warm-start from the 'patch by hand' plan, which is also the safety-net result"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Sequence

from ..domain.enums import EventType
from ..domain.models import Assignment, Event, Plan, PlanMetrics, State, by_id
from ..optimization.baseline import greedy_plan
from ..optimization.objective import PRESETS, Weights
from ..resilience.stress_test import stress_test
from .events import apply_events
from .impact import Impact, analyze_impact, compute_metrics


@dataclass(slots=True)
class ReplanResult:
    label: str
    state: State                 # post-event state
    plan: Plan
    impact: Impact
    metrics: PlanMetrics


def select_locks(state: State, plan: Plan, affected: set[str], freeze: int) -> list[Assignment]:
    """Started sorties are history; unaffected sorties inside the freeze window are frozen."""
    horizon = state.now + freeze
    return [Assignment(a.mission_id, a.aircraft_id, a.crew_id, a.start, True)
            for a in plan.assignments if a.mission_id not in affected and a.start < horizon]


LOCAL_SCOPE_MIN_MISSIONS = 120


def free_neighbourhood(state: State, plan: Plan, impact: Impact, margin: int = 8) -> set[str]:
    """Missions the replan may touch: broken sorties, their ripple, never-assigned missions, and
    same-type sorties overlapping the disrupted time span (+/- margin slots). Everything else is
    locked, which keeps the CP-SAT model small no matter how large the fleet is."""
    m_by, by_m = by_id(state.missions), {a.mission_id: a for a in plan.assignments}
    unassigned = [m for m in state.missions if m.id not in by_m]
    free = set(impact.directly_affected) | set(impact.ripple)
    if not impact.directly_affected:                    # e.g. a new mission: nothing local to anchor on
        return free | {m.id for m in unassigned}
    types = {m_by[i].ac_type for i in impact.directly_affected}
    lo = min(by_m[i].start for i in impact.directly_affected) - margin
    hi = max(by_m[i].start + m_by[i].duration_slots for i in impact.directly_affected) + margin
    free |= {m.id for m in unassigned if m.ac_type in types and m.earliest < hi and m.latest > lo}
    for a in plan.assignments:
        m = m_by[a.mission_id]
        if m.ac_type in types and a.start < hi and a.start + m.duration_slots > lo:
            free.add(a.mission_id)
    return free


def replan(state: State, plan: Plan, events: Sequence[Event], *,
           weights: Weights = PRESETS["B_balanced"], freeze: int = 4, time_limit: float = 5.0,
           workers: int | None = None, seed: int = 0, label: str = "min-churn",
           robustness_trials: int = 0, scope: str = "auto") -> ReplanResult:
    """scope: "global" re-optimises every unlocked sortie; "local" only the disrupted neighbourhood;
    "auto" picks local for large instances (> 120 missions) so replans stay in seconds."""
    from ..optimization.solver import solve      # lazy: OR-Tools only needed here

    t0 = perf_counter()
    new_state = apply_events(state, events)
    impact = analyze_impact(new_state, plan)
    affected = set(impact.directly_affected)
    locks = select_locks(new_state, plan, affected, freeze)
    if scope == "auto":
        big = len(new_state.missions) > LOCAL_SCOPE_MIN_MISSIONS
        scope = "local" if big and not any(e.type == EventType.PRIORITY_CHANGE for e in events) else "global"
    if scope == "local":
        free = free_neighbourhood(new_state, plan, impact)
        have = {l.mission_id for l in locks}
        locks += [Assignment(a.mission_id, a.aircraft_id, a.crew_id, a.start, True)
                  for a in plan.assignments if a.mission_id not in free and a.mission_id not in have]
    patch = greedy_plan(new_state, fixed=[a for a in plan.assignments if a.mission_id not in affected],
                        check=False)

    new_plan = solve(new_state, weights=weights, locked=locks, reference=plan, hint=patch,
                     time_limit=time_limit, workers=workers, seed=seed)
    if new_plan.status.startswith(("INFEASIBLE", "MODEL_INVALID")):      # locks clash: keep only started
        started = [a for a in locks if a.start < new_state.now]
        new_plan = solve(new_state, weights=weights, locked=started, reference=plan, hint=patch,
                         time_limit=time_limit, workers=workers, seed=seed)

    ms = (perf_counter() - t0) * 1000
    rob = None
    if robustness_trials:
        rob = 100 * stress_test(new_state, new_plan, n_trials=robustness_trials, seed=seed).mean_retained
    metrics = compute_metrics(new_plan, plan, new_state, original_value=plan.value,
                              solve_ms=ms, robustness=rob)
    return ReplanResult(label, new_state, new_plan, impact, metrics)


CHURN_SWEEP = (0, 8, 20, 50, 120)      # reward per briefed sortie kept; 0 = ignore stability


def replan_options(state: State, plan: Plan, events: Sequence[Event], *, time_limit: float = 5.0,
                   robustness_trials: int = 60, **kw) -> list[ReplanResult]:
    """Up to three genuinely different plans for the commander, found by sweeping the stability
    weight and de-duplicating identical results:
        A_max_value  highest value kept        C_stable  fewest sorties changed
        B_balanced   the middle of the frontier
    Only non-dominated plans survive (no plan keeps more value with fewer changes), so fewer than
    three may be returned when the disruption has little real trade-off to offer."""
    cands: list[ReplanResult] = []
    seen: set[frozenset] = set()
    for ch in CHURN_SWEEP:
        w = Weights(churn=ch, risk=0.5 if ch == 0 else (2.0 if ch >= 120 else 1.0))
        r = replan(state, plan, events, weights=w, label=f"churn={ch}", time_limit=time_limit, **kw)
        sig = frozenset((a.mission_id, a.aircraft_id, a.crew_id, a.start) for a in r.plan.assignments)
        if sig not in seen:
            seen.add(sig)
            cands.append(r)

    def dominated(r: ReplanResult) -> bool:     # another plan keeps >= value with <= changes (one strictly)
        m = r.metrics
        return any(q is not r and q.metrics.value >= m.value and q.metrics.sorties_changed <= m.sorties_changed
                   and (q.metrics.value > m.value or q.metrics.sorties_changed < m.sorties_changed) for q in cands)

    cands = [r for r in cands if not dominated(r)]
    by_value = sorted(cands, key=lambda r: (-r.metrics.value, r.metrics.sorties_changed))
    by_stab = sorted(cands, key=lambda r: (r.metrics.sorties_changed, -r.metrics.value))
    picks = [by_value[0]]
    if by_stab[0] is not by_value[0]:
        picks.append(by_stab[0])
    rest = [r for r in sorted(cands, key=lambda r: r.metrics.sorties_changed) if r not in picks]
    if rest:
        picks.insert(1, rest[len(rest) // 2])
    names = ["A_max_value", "B_balanced", "C_stable"] if len(picks) == 3 else (
        ["A_max_value", "C_stable"] if len(picks) == 2 else ["A_only_option"])
    for r, n in zip(sorted(picks, key=lambda r: (-r.metrics.value, r.metrics.sorties_changed)), names):
        r.label = n
        if robustness_trials:
            r.metrics.robustness = 100 * stress_test(r.state, r.plan, n_trials=robustness_trials,
                                                     seed=kw.get("seed", 0)).mean_retained
    return sorted(picks, key=lambda r: r.label)


def patch_by_hand(state: State, plan: Plan, events: Sequence[Event]) -> ReplanResult:
    """Baseline 1: keep everything that still works, greedily re-place only what broke."""
    t0 = perf_counter()
    new_state = apply_events(state, events)
    impact = analyze_impact(new_state, plan)
    affected = set(impact.directly_affected)
    new_plan = greedy_plan(new_state, fixed=[a for a in plan.assignments if a.mission_id not in affected])
    ms = (perf_counter() - t0) * 1000
    return ReplanResult("greedy-patch", new_state, new_plan, impact,
                        compute_metrics(new_plan, plan, new_state, original_value=plan.value, solve_ms=ms))


def resolve_from_scratch(state: State, plan: Plan, events: Sequence[Event], *,
                         time_limit: float = 5.0, workers: int | None = None,
                         seed: int = 0) -> ReplanResult:
    """Baseline 2: re-optimise everything not yet flown, no stability term, cold start."""
    from ..optimization.solver import solve

    t0 = perf_counter()
    new_state = apply_events(state, events)
    impact = analyze_impact(new_state, plan)
    started = [Assignment(a.mission_id, a.aircraft_id, a.crew_id, a.start, True)
               for a in plan.assignments if a.start < new_state.now]
    new_plan = solve(new_state, weights=Weights(churn=0), locked=started, time_limit=time_limit,
                     workers=workers, seed=seed)
    ms = (perf_counter() - t0) * 1000
    return ReplanResult("re-solve-from-scratch", new_state, new_plan, impact,
                        compute_metrics(new_plan, plan, new_state, original_value=plan.value, solve_ms=ms))
