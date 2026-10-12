from engine.data import SIZES, generate, make_event
from engine.domain import State, from_dict, to_dict
from engine.optimization import greedy_plan


def test_deterministic_for_same_seed():
    assert to_dict(generate("M", 0.9, 7)) == to_dict(generate("M", 0.9, 7))


def test_different_seeds_differ():
    assert to_dict(generate("S", 0.9, 1)) != to_dict(generate("S", 0.9, 2))


def test_sizes():
    for size, cfg in SIZES.items():
        st = generate(size, 0.9, 0)
        assert len(st.aircraft) == cfg["aircraft"] and len(st.missions) == cfg["missions"]


def test_tightness_reduces_greedy_coverage():
    relaxed = greedy_plan(generate("M", 0.6, 3)).value / sum(m.value for m in generate("M", 0.6, 3).missions)
    tight = greedy_plan(generate("M", 1.1, 3)).value / sum(m.value for m in generate("M", 1.1, 3).missions)
    assert tight < relaxed


def test_json_roundtrip():
    st = generate("S", 0.9, 5, trap_groups=1)
    assert to_dict(from_dict(State, to_dict(st))) == to_dict(st)


def test_trap_groups_add_missions():
    assert len(generate("S", 0.9, 0, trap_groups=2).missions) == SIZES["S"]["missions"] + 6


def test_event_targets_exist():
    st = generate("S", 0.9, 4)
    plan = greedy_plan(st)
    ids = {a.id for a in st.aircraft} | {c.id for c in st.crew} | {b.id for b in st.bases}
    for kind in ("aircraft_out", "crew_out", "runway"):
        for ev in make_event(st, plan, kind, 4):
            assert ev.target_id in ids
