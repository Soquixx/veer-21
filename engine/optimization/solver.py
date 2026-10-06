"""Solve driver: prune -> build CP-SAT -> solve (warm-started) -> extract -> validate.

Safety net: if a warm-start plan is supplied and the solver ends with something worse (or
nothing, e.g. time limit), the validated warm-start plan is returned instead, so the engine is
never worse than its own heuristic."""
from __future__ import annotations

import os
from time import perf_counter
from typing import Sequence

from ortools.sat.python import cp_model

from ..constraints.feasibility import build_compat, validate
from ..domain.models import Assignment, Plan, State
from .baseline import greedy_plan
from .model import Built, build_model
from .objective import Weights, finalize, score_plan


def _set_workers(params, n: int) -> None:
    for name in ("num_workers", "num_search_workers"):     # renamed across OR-Tools versions
        try:
            setattr(params, name, n)
            return
        except (AttributeError, ValueError):
            continue


def _extract(solver, built: Built, locked: Sequence[Assignment]) -> list[Assignment]:
    out = list(locked)
    for mid in built.modeled:
        if not solver.BooleanValue(built.p[mid]):
            continue
        aid = next(a for a, v in built.xs[mid] if solver.BooleanValue(v))
        cid = next(c for c, v in built.ys[mid] if solver.BooleanValue(v))
        out.append(Assignment(mid, aid, cid, int(solver.Value(built.s[mid]))))
    return out


def solve(state: State, *, weights: Weights = Weights(), locked: Sequence[Assignment] = (),
          reference: Plan | None = None, hint: Plan | None = None, time_limit: float = 10.0,
          workers: int | None = None, seed: int = 0, rel_gap: float = 0.005,
          check: bool = True) -> Plan:
    t0 = perf_counter()
    locked = [Assignment(a.mission_id, a.aircraft_id, a.crew_id, a.start, True) for a in locked]
    compat = build_compat(state, locked)
    built = build_model(state, compat, weights, locked, reference, hint)

    solver = cp_model.CpSolver()
    prm = solver.parameters
    prm.max_time_in_seconds = float(time_limit)
    prm.random_seed = seed
    prm.relative_gap_limit = rel_gap
    _set_workers(prm, workers or max(1, min(8, os.cpu_count() or 1)))

    status = solver.Solve(built.model)
    name = solver.StatusName(status)
    ok = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    meta = {"modeled_missions": len(built.modeled)}
    if ok:
        meta["objective"] = solver.ObjectiveValue()
        meta["bound"] = solver.BestObjectiveBound()
    plan = finalize(state, _extract(solver, built, locked) if ok else locked, weights, reference,
                    status=name, ms=(perf_counter() - t0) * 1000, compat=compat, meta=meta, check=check)

    if hint is not None:
        hint_ids = {a.mission_id for a in hint.assignments}
        usable = all(l.mission_id in hint_ids for l in locked) and not validate(hint, state)
        if usable and (not ok or score_plan(hint, state, weights, reference) > plan.score + 1e-9):
            plan = finalize(state, hint.assignments, weights, reference, status=f"{name}+HINT",
                            ms=(perf_counter() - t0) * 1000, compat=compat, meta=meta, check=check)
    return plan


def solve_initial(state: State, **kw) -> Plan:
    """Greedy warm start + CP-SAT. Returns the optimised plan."""
    return solve(state, hint=greedy_plan(state, check=False), **kw)
