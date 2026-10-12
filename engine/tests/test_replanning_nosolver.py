from engine.data import generate, make_event
from engine.optimization import greedy_plan
from engine.replanning import analyze_impact, apply_events, patch_by_hand, select_locks
from engine.resilience import stress_test


def test_aircraft_outage_affects_only_that_aircrafts_future_sorties():
    st = generate("M", 0.9, 3)
    p = greedy_plan(st)
    ev = make_event(st, p, "aircraft_out", 3)
    new = apply_events(st, ev)
    imp = analyze_impact(new, p)
    by_m = {a.mission_id: a for a in p.assignments}
    assert imp.directly_affected
    for mid in imp.directly_affected:
        assert by_m[mid].aircraft_id == ev[0].target_id and by_m[mid].start >= ev[0].time


def test_apply_events_does_not_mutate_original():
    st = generate("S", 0.9, 1)
    p = greedy_plan(st)
    ev = make_event(st, p, "combined", 1)
    before = repr(st)
    apply_events(st, ev)
    assert repr(st) == before


def test_patch_is_valid_and_untouched_sorties_unchanged():
    st = generate("M", 0.9, 5)
    p = greedy_plan(st)
    for kind in ("aircraft_out", "crew_out", "weather", "threat", "runway", "combined"):
        r = patch_by_hand(st, p, make_event(st, p, kind, 5))
        assert r.metrics.violations == 0
        old = {a.mission_id: (a.aircraft_id, a.crew_id, a.start) for a in p.assignments}
        new = {a.mission_id: (a.aircraft_id, a.crew_id, a.start) for a in r.plan.assignments}
        untouched = set(old) - set(r.impact.directly_affected)
        assert all(new.get(m) == old[m] for m in untouched)


def test_locks_never_include_affected_or_future_beyond_freeze():
    st = generate("M", 0.9, 5)
    p = greedy_plan(st)
    ev = make_event(st, p, "aircraft_out", 5)
    new = apply_events(st, ev)
    imp = analyze_impact(new, p)
    locks = select_locks(new, p, set(imp.directly_affected), freeze=4)
    assert all(l.mission_id not in imp.directly_affected and l.start < new.now + 4 for l in locks)


def test_stress_test_is_deterministic_and_repair_helps():
    st = generate("M", 0.9, 5)
    p = greedy_plan(st)
    a = stress_test(st, p, n_trials=80, seed=1)
    b = stress_test(st, p, n_trials=80, seed=1)
    assert a == b
    assert 0 <= a.worst_retained <= a.mean_retained <= 1
    assert a.mean_retained >= a.mean_no_repair
