import pytest

pytest.importorskip("ortools")

from engine.constraints import validate                       # noqa: E402
from engine.data import generate, make_event                  # noqa: E402
from engine.optimization import PRESETS, Weights, greedy_plan, score_plan  # noqa: E402
from engine.optimization.solver import solve, solve_initial   # noqa: E402
from engine.replanning import patch_by_hand, replan, replan_options, resolve_from_scratch  # noqa: E402


def test_solver_beats_greedy_on_trap_and_validator_agrees():
    st = generate("S", 0.9, 7, trap_groups=1)
    g = greedy_plan(st)
    o = solve_initial(st, time_limit=10, seed=1)
    assert o.violations == []
    assert {"TRAP0-A", "TRAP0-B", "TRAP0-C"} <= {a.mission_id for a in o.assignments}
    assert o.value >= g.value + 100


def test_solver_never_worse_than_greedy_score_and_always_valid():
    for size, tight in (("S", 0.9), ("M", 1.1)):
        st = generate(size, tight, 3)
        g = greedy_plan(st)
        o = solve_initial(st, time_limit=10, seed=3)
        assert o.violations == []
        assert o.score >= score_plan(g, st, Weights()) - 1e-6


def test_replan_respects_locks_and_is_valid():
    st = generate("M", 0.9, 4)
    o = solve_initial(st, time_limit=10, seed=4)
    ev = make_event(st, o, "aircraft_out", 4)
    r = replan(st, o, ev, time_limit=10, seed=4)
    assert r.metrics.violations == 0
    old = {a.mission_id: (a.aircraft_id, a.crew_id, a.start) for a in o.assignments}
    new = {a.mission_id: (a.aircraft_id, a.crew_id, a.start) for a in r.plan.assignments}
    frozen = [a for a in o.assignments if a.start < r.state.now + 4 and a.mission_id not in r.impact.directly_affected]
    assert all(new.get(a.mission_id) == old[a.mission_id] for a in frozen)


def test_all_event_kinds_yield_valid_replans():
    st = generate("S", 0.9, 2)
    o = solve_initial(st, time_limit=5, seed=2)
    for kind in ("aircraft_out", "crew_out", "weather", "threat", "runway", "combined"):
        assert replan(st, o, make_event(st, o, kind, 2), time_limit=5, seed=2).metrics.violations == 0
        assert resolve_from_scratch(st, o, make_event(st, o, kind, 2), time_limit=5, seed=2).metrics.violations == 0


def test_options_are_distinct_and_ordered_by_value():
    st = generate("M", 1.0, 6)
    o = solve_initial(st, time_limit=10, seed=6)
    ev = make_event(st, o, "combined", 6)
    opts = replan_options(st, o, ev, time_limit=5, seed=6, robustness_trials=20)
    assert 1 <= len(opts) <= 3 and all(r.metrics.violations == 0 for r in opts)
    sigs = {frozenset((a.mission_id, a.aircraft_id, a.crew_id, a.start) for a in r.plan.assignments) for r in opts}
    assert len(sigs) == len(opts)
    if len(opts) > 1:
        assert opts[0].metrics.value >= opts[-1].metrics.value
        assert opts[0].metrics.sorties_changed >= opts[-1].metrics.sorties_changed


def test_outage_during_airborne_sortie_is_not_infeasible():
    """Regression: a locked in-progress sortie overlapping a fresh outage used to make the model
    INFEASIBLE, silently returning only flown sorties (scratch) or the greedy patch (min-churn)."""
    st = generate("S", 0.9, 1)
    o = solve_initial(st, time_limit=5, seed=1)
    a = next(x for x in o.assignments if x.start > 5)
    from engine.domain import Event, EventType
    ev = [Event("E-mid", EventType.AIRCRAFT_OUT, a.start + 1, target_id=a.aircraft_id)]
    for r in (replan(st, o, ev, time_limit=5, seed=1), resolve_from_scratch(st, o, ev, time_limit=5, seed=1)):
        assert "INFEASIBLE" not in r.plan.status and "HINT" not in r.plan.status
        assert r.metrics.violations == 0
    assert resolve_from_scratch(st, o, ev, time_limit=5, seed=1).metrics.value_retained > 0.6


def test_failure_during_scheduled_maintenance_is_not_infeasible():
    """Regression: new outage overlapping the aircraft's maintenance window (two fixed intervals)."""
    from engine.domain import Event, EventType
    st = generate("S", 0.9, 1)
    o = solve_initial(st, time_limit=5, seed=1)
    a = next(x for x in o.assignments if x.start > 5)
    ac = next(x for x in st.aircraft if x.id == a.aircraft_id)
    ac.outages.append((a.start + 30, a.start + 40))
    o = solve_initial(st, time_limit=5, seed=1)
    ev = [Event("E-m", EventType.AIRCRAFT_OUT, 8, target_id=ac.id)]
    for r in (replan(st, o, ev, time_limit=5, seed=1), resolve_from_scratch(st, o, ev, time_limit=5, seed=1)):
        assert "INFEASIBLE" not in r.plan.status and r.metrics.violations == 0


def test_local_scope_replan_is_valid_and_leaves_far_sorties_alone():
    st = generate("M", 1.0, 3)
    o = solve_initial(st, time_limit=10, seed=3)
    ev = make_event(st, o, "aircraft_out", 3)
    r = replan(st, o, ev, time_limit=5, seed=3, scope="local")
    assert r.metrics.violations == 0 and "INFEASIBLE" not in r.plan.status
    from engine.replanning.replan import free_neighbourhood
    free = free_neighbourhood(r.state, o, r.impact)
    old = {a.mission_id: (a.aircraft_id, a.crew_id, a.start) for a in o.assignments}
    new = {a.mission_id: (a.aircraft_id, a.crew_id, a.start) for a in r.plan.assignments}
    assert all(new.get(m) == old[m] for m in old if m not in free)


def test_service_end_to_end_json():
    import json
    from engine import service
    state = service.generate_scenario("S", 0.9, 2, 1)
    created = service.create_plan(state, time_limit=5, seed=2)
    assert created["summary"]["violations"] == 0
    events = service.suggest_events(state, created["plan"], "combined", 2)
    out = service.replan_options(state, created["plan"], events, time_limit=5, seed=2, robustness_trials=10)
    json.dumps(out)
    assert 1 <= len(out["options"]) <= 3 and out["options"][0]["metrics"]["violations"] == 0
