"""Greedy priority-first assigner: the 'what a rules-of-thumb planner does' baseline.

Missions are taken by priority then deadline; each gets the EARLIEST feasible start, the
most reliable free aircraft, and the least-fatigued free crew at that aircraft's base.
Also doubles as (a) a warm-start hint for CP-SAT and (b) the 'patch-by-hand' replanner
(pass `fixed` = unaffected sorties and only the broken ones are re-placed)."""
from __future__ import annotations

from collections import defaultdict
from time import perf_counter
from typing import Iterable, Sequence

import numpy as np

from ..constraints.feasibility import Hazards, build_compat
from ..domain.models import Assignment, Plan, State, by_id
from .objective import Weights, finalize


def greedy_plan(state: State, fixed: Sequence[Assignment] = (),
                mission_ids: Iterable[str] | None = None, *,
                exclude_aircraft: Iterable[str] = (), exclude_crew: Iterable[str] = (),
                hz: Hazards | None = None, weights: Weights = Weights(),
                check: bool = True) -> Plan:
    t0 = perf_counter()
    fixed = list(fixed)
    H, rest = state.horizon, state.crew_rest_slots
    pad = H + 64
    ex_c = set(exclude_crew)
    m_by, a_by, c_by = by_id(state.missions), by_id(state.aircraft), by_id(state.crew)

    todo_ids = set(m_by) if mission_ids is None else set(mission_ids)
    todo_ids -= {a.mission_id for a in fixed}
    compat = build_compat(state, fixed, only=todo_ids, hz=hz,
                          exclude_aircraft=exclude_aircraft, exclude_crew=exclude_crew)

    occ_a = {a.id: np.zeros(pad, bool) for a in state.aircraft}
    occ_c = {c.id: np.zeros(pad, bool) for c in state.crew}
    cap = {b.id: np.full(pad, b.runway_capacity, np.int16) for b in state.bases}
    used = {b.id: np.zeros(pad, np.int16) for b in state.bases}
    for a in state.aircraft:
        for s, e in a.outages:
            occ_a[a.id][max(s, 0):e] = True
    for c in state.crew:
        for s, e in c.outages:
            occ_c[c.id][max(s, 0):e] = True
    for b in state.bases:
        for s, e in b.closures:
            cap[b.id][max(s, 0):e] = 0

    load = {c.id: c.duty_slots_used for c in state.crew}
    duty_left = dict(compat.duty_left)            # already net of `fixed`
    for f in fixed:
        m, a = m_by[f.mission_id], a_by[f.aircraft_id]
        occ_a[a.id][f.start:f.start + m.duration_slots + a.turnaround_slots] = True
        occ_c[f.crew_id][f.start:f.start + m.duration_slots + rest] = True
        used[a.base_id][f.start] += 1
        load[f.crew_id] += m.duration_slots

    crews_at: dict[tuple[str, object], list] = defaultdict(list)
    for c in state.crew:
        if c.id in ex_c:
            continue
        for r in c.ratings:
            crews_at[(c.base_id, r)].append(c)

    order = sorted((m_by[i] for i in todo_ids if i in compat.starts),
                   key=lambda m: (m.priority, m.latest, m.id))
    new: list[Assignment] = []
    for m in order:
        if not compat.modelable(m.id):
            continue
        dur = m.duration_slots
        acs = sorted((a_by[i] for i in compat.aircraft[m.id]), key=lambda a: (-a.p_serviceable, a.id))
        ok_crew = set(compat.crew[m.id])
        placed = False
        for s in compat.starts[m.id].tolist():
            for a in acs:
                if s < a.available_from or s + dur > a.available_until:
                    continue
                if used[a.base_id][s] >= cap[a.base_id][s]:
                    continue
                if occ_a[a.id][s:s + dur + a.turnaround_slots].any():
                    continue
                best = None
                for c in crews_at[(a.base_id, m.ac_type)]:
                    if c.id not in ok_crew or duty_left[c.id] < dur or c.rest_until > s:
                        continue
                    if occ_c[c.id][s:s + dur + rest].any():
                        continue
                    if best is None or load[c.id] < load[best.id]:
                        best = c
                if best is None:
                    continue
                occ_a[a.id][s:s + dur + a.turnaround_slots] = True
                occ_c[best.id][s:s + dur + rest] = True
                used[a.base_id][s] += 1
                load[best.id] += dur
                duty_left[best.id] -= dur
                new.append(Assignment(m.id, a.id, best.id, s))
                placed = True
                break
            if placed:
                break

    return finalize(state, fixed + new, weights, None, status="GREEDY",
                    ms=(perf_counter() - t0) * 1000, compat=compat, check=check)
