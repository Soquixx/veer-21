from backend.fusion.adapters import (Reading, SimulatedIncidentAdapter, SimulatedLegacyRosterAdapter,
                                     SimulatedThreatAdapter, SimulatedWeatherAdapter,
                                     SimulatedWeatherSecondaryAdapter)
from backend.fusion.fuser import FusionEngine, is_stale


def _full_engine(seed=0):
    return FusionEngine([SimulatedWeatherAdapter(), SimulatedWeatherSecondaryAdapter(), SimulatedThreatAdapter(),
                         SimulatedLegacyRosterAdapter(seed), SimulatedIncidentAdapter(seed)])


def _state():
    return {"now": 0, "weather": {"BRAVO": [4], "ALPHA": [2]},
            "threats": [{"id": "TH0", "sector": "BRAVO", "start": 0, "end": 10, "severity": 3}],
            "aircraft": [{"id": "AC000"}, {"id": "AC001"}], "crew": [{"id": "CR000"}, {"id": "CR001"}]}


def test_conflict_resolution_prefers_higher_confidence():
    result = FusionEngine([SimulatedWeatherAdapter(), SimulatedWeatherSecondaryAdapter()]).fuse(
        {"now": 0, "weather": {"BRAVO": [4]}})
    bravo = next(x for x in result["resolved"] if x["key"] == "BRAVO")
    assert bravo["chosen"]["source"] == "simulated.weather.primary"
    assert len(bravo["candidates"]) == 2 and bravo["conflict"] is True


def test_threat_never_overwrites_weather_in_same_sector():
    result = _full_engine().fuse(_state())
    kinds = {(x["kind"], x["key"]) for x in result["resolved"]}
    assert ("weather", "BRAVO") in kinds and ("threat", "TH0") in kinds
    weather = next(x for x in result["resolved"] if (x["kind"], x["key"]) == ("weather", "BRAVO"))
    assert weather["chosen"]["value"]["severity"] == 4


def test_stale_reading_loses_to_fresh_one_and_is_flagged():
    result = _full_engine().fuse(_state())
    fault = next(x for x in result["resolved"] if x["kind"] == "aircraft_fault")
    assert fault["status"] == "FRESH" and fault["chosen"]["value"]["status"] == "OUT"
    assert any(c["stale"] for c in fault["candidates"]) and fault["resolution_rule"] == "stale readings discarded"


def test_only_stale_sources_are_flagged_stale_and_never_become_events():
    result = _full_engine().fuse(_state())
    crew = next(x for x in result["resolved"] if x["kind"] == "crew_fault")
    assert crew["status"] == "STALE"
    events = FusionEngine.to_events(result, _state())
    assert {e["type"] for e in events} == {"AIRCRAFT_OUT", "WEATHER"}          # no CREW_OUT from stale data


def test_all_stale_keeps_most_trusted_but_flags_it():
    r1 = Reading("a", "2026-01-01T00:00:00+00:00", {"x": 1}, 900, 0.9, kind="k", key="z", max_age_seconds=60)
    r2 = Reading("b", "2026-01-01T00:00:00+00:00", {"x": 2}, 900, 0.6, kind="k", key="z", max_age_seconds=60)

    class Fixed:
        name = "fixed"
        def read(self, state): return [r1, r2]

    item = FusionEngine([Fixed()]).fuse({})["resolved"][0]
    assert is_stale(r1) and item["status"] == "STALE" and item["chosen"]["source"] == "a"


def test_a_failing_adapter_is_reported_not_fatal():
    class Boom:
        name = "boom"
        def read(self, state): raise TimeoutError("feed down")

    result = FusionEngine([Boom(), SimulatedWeatherAdapter()]).fuse({"now": 0, "weather": {"ALPHA": [1]}})
    assert result["adapter_errors"][0]["adapter"] == "boom" and result["resolved"]


def test_fusion_events_are_accepted_by_the_real_engine():
    from engine import service
    from engine.data import generate
    from engine.optimization import greedy_plan
    state = service.generate_scenario("S", 0.9, 3, 0)
    plan = service.to_json(greedy_plan(generate("S", 0.9, 3, 0)))
    fusion = FusionEngine([SimulatedWeatherAdapter(), SimulatedIncidentAdapter(3), SimulatedLegacyRosterAdapter(3)])
    events = FusionEngine.to_events(fusion.fuse(state), state)
    assert events
    out = service.assess_impact(state, plan, events)       # raises if any event is malformed
    assert "impact" in out
