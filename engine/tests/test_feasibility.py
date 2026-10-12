import copy

from engine.constraints import validate
from engine.data import generate
from engine.domain import Assignment, Plan
from engine.optimization import greedy_plan


def _kinds(plan, state):
    return {v.kind for v in validate(plan, state)}


def test_greedy_plans_are_valid_across_sizes_and_tightness():
    for size in ("S", "M", "L"):
        for tight in (0.6, 0.9, 1.1):
            for seed in (0, 1):
                st = generate(size, tight, seed, trap_groups=1)
                assert validate(greedy_plan(st), st) == []


def test_detects_aircraft_and_crew_overlap():
    st = generate("S", 0.9, 1)
    p = greedy_plan(st)
    a0 = p.assignments[0]
    m0 = next(m for m in st.missions if m.id == a0.mission_id)
    m2 = next(m for m in st.missions if m.ac_type == m0.ac_type and m.id != m0.id)
    bad = Plan(assignments=[a0, Assignment(m2.id, a0.aircraft_id, a0.crew_id, a0.start)])
    kinds = _kinds(bad, st)
    assert "AIRCRAFT_OVERLAP" in kinds and "CREW_OVERLAP" in kinds


def test_detects_crew_rating_and_duplicates():
    st = generate("S", 0.9, 1)
    p = greedy_plan(st)
    a = p.assignments[0]
    m = next(m for m in st.missions if m.id == a.mission_id)
    wrong = next(c for c in st.crew if m.ac_type not in c.ratings)
    bad = Plan(assignments=[Assignment(a.mission_id, a.aircraft_id, wrong.id, a.start), a])
    kinds = _kinds(bad, st)
    assert "CREW_RATING" in kinds and "DUPLICATE_MISSION" in kinds


def test_detects_weather_and_time_window():
    st = generate("S", 0.9, 1)
    p = greedy_plan(st)
    a = p.assignments[0]
    m = next(m for m in st.missions if m.id == a.mission_id)
    st2 = copy.deepcopy(st)
    st2.weather[m.sector] = [5] * st2.horizon
    assert "WEATHER" in _kinds(p, st2) or m.weather_limit >= 5
    late = Plan(assignments=[Assignment(a.mission_id, a.aircraft_id, a.crew_id, m.latest)])
    assert "TIME_WINDOW" in _kinds(late, st)


def test_detects_runway_closure_and_outage():
    st = generate("S", 0.9, 1)
    p = greedy_plan(st)
    a = p.assignments[0]
    ac = next(x for x in st.aircraft if x.id == a.aircraft_id)
    st2 = copy.deepcopy(st)
    next(b for b in st2.bases if b.id == ac.base_id).closures.append((a.start, a.start + 1))
    next(x for x in st2.aircraft if x.id == a.aircraft_id).outages.append((a.start, a.start + 2))
    kinds = _kinds(p, st2)
    assert "RUNWAY" in kinds and "AIRCRAFT_OUTAGE" in kinds


def test_past_sorties_are_history():
    st = generate("S", 0.9, 1)
    p = greedy_plan(st)
    a = p.assignments[0]
    st2 = copy.deepcopy(st)
    next(x for x in st2.aircraft if x.id == a.aircraft_id).outages.append((a.start, a.start + 2))
    assert any(v.mission_id == a.mission_id and v.kind == "AIRCRAFT_OUTAGE" for v in validate(p, st2))
    st2.now = a.start + 1                    # already started -> no longer judged against the outage
    assert not any(v.mission_id == a.mission_id and v.kind == "AIRCRAFT_OUTAGE" for v in validate(p, st2))
