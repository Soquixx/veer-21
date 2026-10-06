"""JSON facade for the API layer. Member 2 imports ONLY this module.

Every function takes and returns plain JSON-able dicts/lists (no engine classes), so FastAPI
endpoints are one-liners:

    POST /scenario        -> generate_scenario(...)
    POST /plan            -> create_plan(state)
    POST /impact          -> assess_impact(state, plan, events)         (instant, no solver)
    POST /replan          -> replan_options(state, plan, events)        (plan A/B/C + diffs)
    POST /validate        -> validate_plan(state, plan)
    POST /stress-test     -> stress(state, plan)

Export demo fixtures so the frontend can be built without running the solver:
    python -m engine.service --export sample_data --size M --seed 7 --traps 2 --event combined
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .constraints.feasibility import validate
from .data.generator import EVENT_KINDS, generate, make_event
from .domain.models import Event, Plan, State, from_dict
from .optimization.baseline import greedy_plan
from .replanning.events import apply_events
from .replanning.impact import analyze_impact
from .resilience.stress_test import stress_test


# ------------------------------------------------------------------ plumbing
def _default(o: Any) -> Any:
    if isinstance(o, Enum):
        return o.value
    if is_dataclass(o):
        return asdict(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def to_json(obj: Any) -> Any:
    """Any engine object -> plain JSON structure (enums -> values, tuples -> lists)."""
    return json.loads(json.dumps(obj, default=_default))


def save_json(path: str | Path, obj: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(to_json(obj), indent=2))


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def _state(d: dict) -> State:
    return from_dict(State, d)


def _plan(d: dict) -> Plan:
    return from_dict(Plan, d)


def _events(items: list[dict]) -> list[Event]:
    return [from_dict(Event, e) for e in items]


def _summary(plan: Plan, st: State) -> dict:
    return {"flown": len(plan.assignments), "total_missions": len(st.missions), "value": plan.value,
            "status": plan.status, "solve_ms": plan.solve_ms, "violations": len(plan.violations)}


# ------------------------------------------------------------------ endpoints
def generate_scenario(size: str = "M", tightness: float = 0.9, seed: int = 7, trap_groups: int = 0) -> dict:
    return to_json(generate(size, tightness, seed, trap_groups))


def create_plan(state: dict, *, time_limit: float = 10.0, seed: int = 0, workers: int | None = None) -> dict:
    """Greedy baseline + optimised plan. Pre-compute this; allow a generous time limit."""
    from .optimization.solver import solve
    st = _state(state)
    g = greedy_plan(st)
    o = solve(st, hint=g, time_limit=time_limit, seed=seed, workers=workers)
    return {"plan": to_json(o), "summary": _summary(o, st),
            "greedy": {"flown": len(g.assignments), "value": g.value}}


def suggest_events(state: dict, plan: dict, kind: str = "combined", seed: int = 0) -> list[dict]:
    """A realistic disruption aimed at the busiest resource (for demos and the benchmark)."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"kind must be one of {EVENT_KINDS}")
    return to_json(make_event(_state(state), _plan(plan), kind, seed))


def assess_impact(state: dict, plan: dict, events: list[dict]) -> dict:
    """'Disruption detected' panel: what broke and what ripples. Instant, no optimisation."""
    new = apply_events(_state(state), _events(events))
    imp = analyze_impact(new, _plan(plan))
    return {"now": new.now, "impact": to_json(imp)}


def plan_diff(old_plan: dict | Plan, new_plan: dict | Plan, since: int = 0) -> list[dict]:
    """Per-mission before/after for the UI: reassigned / retimed / dropped / added."""
    old = old_plan if isinstance(old_plan, Plan) else _plan(old_plan)
    new = new_plan if isinstance(new_plan, Plan) else _plan(new_plan)
    o = {a.mission_id: a for a in old.assignments}
    n = {a.mission_id: a for a in new.assignments}
    rows = []
    for mid, a in o.items():
        if a.start < since:
            continue
        b = n.get(mid)
        if b is None:
            rows.append({"mission_id": mid, "change": "dropped", "before": a, "after": None})
        elif (a.aircraft_id, a.crew_id) != (b.aircraft_id, b.crew_id):
            rows.append({"mission_id": mid, "change": "reassigned", "before": a, "after": b})
        elif a.start != b.start:
            rows.append({"mission_id": mid, "change": "retimed", "before": a, "after": b})
    rows += [{"mission_id": mid, "change": "added", "before": None, "after": b}
             for mid, b in n.items() if mid not in o]
    return to_json(rows)


def replan_options(state: dict, plan: dict, events: list[dict], *, time_limit: float = 5.0, seed: int = 0,
                   robustness_trials: int = 60, include_state: bool = True, workers: int | None = None) -> dict:
    """Plan A/B/C for the commander (only genuinely different, non-dominated plans), each with
    metrics and a per-mission diff, plus the hand-patch baseline for comparison."""
    from .replanning.replan import patch_by_hand
    from .replanning.replan import replan_options as _options
    st, pl, evs = _state(state), _plan(plan), _events(events)
    opts = _options(st, pl, evs, time_limit=time_limit, seed=seed,
                    robustness_trials=robustness_trials, workers=workers)
    patch = patch_by_hand(st, pl, evs)
    out: dict[str, Any] = {
        "impact": to_json(patch.impact),
        "baseline_greedy_patch": {"metrics": to_json(patch.metrics), "plan": to_json(patch.plan)},
        "options": [{"label": r.label, "plan": to_json(r.plan), "metrics": to_json(r.metrics),
                     "changes": plan_diff(pl, r.plan, since=r.state.now)} for r in opts],
    }
    if include_state:
        out["state_after"] = to_json(opts[0].state)
    return out


def validate_plan(state: dict, plan: dict) -> list[dict]:
    return to_json(validate(_plan(plan), _state(state)))


def stress(state: dict, plan: dict, *, trials: int = 200, seed: int = 0) -> dict:
    return to_json(stress_test(_state(state), _plan(plan), n_trials=trials, seed=seed))


# ------------------------------------------------------------------ fixtures
def export_fixtures(out_dir: str, size: str = "M", tightness: float = 0.9, seed: int = 7,
                    traps: int = 0, event: str = "combined", time_limit: float = 10.0) -> None:
    """Write scenario / plan / events / replan options as JSON so the frontend (and the demo
    video) can be built from a fixed, repeatable scenario."""
    d = Path(out_dir)
    state = generate_scenario(size, tightness, seed, traps)
    save_json(d / "scenario.json", state)
    created = create_plan(state, time_limit=time_limit, seed=seed)
    save_json(d / "plan.json", created)
    events = suggest_events(state, created["plan"], event, seed)
    save_json(d / "events.json", events)
    save_json(d / "impact.json", assess_impact(state, created["plan"], events))
    save_json(d / "replan_options.json", replan_options(state, created["plan"], events, seed=seed))
    print(f"wrote scenario.json, plan.json, events.json, impact.json, replan_options.json -> {d}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", required=True, metavar="DIR")
    ap.add_argument("--size", default="M")
    ap.add_argument("--tightness", type=float, default=0.9)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--traps", type=int, default=0)
    ap.add_argument("--event", default="combined", choices=EVENT_KINDS)
    ap.add_argument("--time-limit", type=float, default=10.0)
    a = ap.parse_args()
    export_fixtures(a.export, a.size, a.tightness, a.seed, a.traps, a.event, a.time_limit)
