import json

from engine import service
from engine.data import generate
from engine.domain import to_dict
from engine.optimization import greedy_plan


def _setup():
    state = service.generate_scenario("M", 0.9, 3, 1)
    plan = service.to_json(greedy_plan(generate("M", 0.9, 3, 1)))
    return state, plan


def test_everything_is_json_serialisable_and_roundtrips():
    state, plan = _setup()
    json.dumps(state), json.dumps(plan)
    assert service._state(state).missions[0].id == "M000"
    assert service.to_json(service._plan(plan)) == plan


def test_impact_diff_validate_stress():
    state, plan = _setup()
    events = service.suggest_events(state, plan, "combined", 3)
    json.dumps(events)
    out = service.assess_impact(state, plan, events)
    assert out["impact"]["directly_affected"] and out["now"] == events[0]["time"]
    assert service.validate_plan(state, plan) == []
    assert 0 < service.stress(state, plan, trials=30)["mean_retained"] <= 1
    assert service.plan_diff(plan, plan) == []


def test_plan_diff_reports_drop_and_reassign():
    state, plan = _setup()
    new = json.loads(json.dumps(plan))
    dropped = new["assignments"].pop(0)["mission_id"]
    new["assignments"][0]["crew_id"] = "OTHER"
    kinds = {r["mission_id"]: r["change"] for r in service.plan_diff(plan, new)}
    assert kinds[dropped] == "dropped" and "reassigned" in kinds.values()
