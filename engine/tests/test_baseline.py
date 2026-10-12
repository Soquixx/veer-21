from engine.data import generate
from engine.optimization import greedy_plan


def test_trap_strands_two_missions():
    st = generate("S", 0.9, 7, trap_groups=1)
    p = greedy_plan(st)
    flown = {a.mission_id for a in p.assignments}
    assert "TRAP0-A" in flown and "TRAP0-B" not in flown and "TRAP0-C" not in flown
    assert next(a for a in p.assignments if a.mission_id == "TRAP0-A").crew_id == "TCR0X"
    assert "TRAP0-B" in p.reasons


def test_fixed_assignments_are_kept_and_patch_only_replaces_requested():
    st = generate("M", 0.9, 2)
    full = greedy_plan(st)
    keep = full.assignments[5:]
    patch = greedy_plan(st, fixed=keep, mission_ids={a.mission_id for a in full.assignments[:5]})
    kept = {(a.mission_id, a.aircraft_id, a.crew_id, a.start) for a in keep}
    assert kept <= {(a.mission_id, a.aircraft_id, a.crew_id, a.start) for a in patch.assignments}
    assert patch.violations == []
