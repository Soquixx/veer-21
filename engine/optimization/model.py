"""CP-SAT formulation.

Per mission m (only those that survive pre-pruning):
    p[m]      mission flown                       s[m]    start slot (shared by all options)
    x[m,a]    aircraft a chosen                   y[m,c]  crew c chosen
    sum_a x = p,  sum_c y = p                     (exactly one aircraft and one crew if flown)
    for every base b:  sum_{a in b} x = sum_{c in b} y      (crews are base-bound)
Resources
    AddNoOverlap per aircraft (flight + turnaround) and per crew (flight + rest), with outages
    and locked sorties entered as FIXED intervals.
    AddCumulative per base for takeoffs (1 slot each), runway closures eat the full capacity.
    Crew duty budget:  sum dur*y <= duty_left.
Objective (all integer):
    + value*p  - risk(aircraft)*x  - delay  + churn_reward*same
Locked sorties are constants, not variables, so replans shrink the model instead of growing it."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from ortools.sat.python import cp_model

from ..constraints.feasibility import Compat, merge_windows, outage_blocks
from ..domain.models import Assignment, Plan, State, by_id
from .objective import Weights, gain, risk_cost

_LE = cp_model.LinearExpr
_sum = getattr(_LE, "sum", None) or _LE.Sum
_wsum = getattr(_LE, "weighted_sum", None) or _LE.WeightedSum


def _has(arr: np.ndarray, v: int) -> bool:
    i = int(arr.searchsorted(v))
    return i < arr.size and int(arr[i]) == v


@dataclass(slots=True)
class Built:
    model: Any
    p: dict[str, Any]
    s: dict[str, Any]
    xs: dict[str, list[tuple[str, Any]]]
    ys: dict[str, list[tuple[str, Any]]]
    modeled: list[str]


def build_model(state: State, compat: Compat, w: Weights, locked: Sequence[Assignment] = (),
                reference: Plan | None = None, hint: Plan | None = None) -> Built:
    cm = cp_model.CpModel()
    now, rest = state.now, state.crew_rest_slots
    m_by, a_by, c_by = by_id(state.missions), by_id(state.aircraft), by_id(state.crew)
    locked = list(locked)
    locked_ids = {a.mission_id for a in locked}
    ref = {a.mission_id: a for a in reference.assignments} if reference is not None else {}

    ac_per_base = Counter(a.base_id for a in state.aircraft)
    rw_bases = {b.id for b in state.bases if b.closures or ac_per_base[b.id] > b.runway_capacity}

    p, s, xs, ys = {}, {}, {}, {}
    ac_iv, cr_iv, rw_iv = defaultdict(list), defaultdict(list), defaultdict(list)
    duty = defaultdict(list)
    obj_v, obj_c = [], []
    modeled: list[str] = []

    for m in state.missions:
        mid = m.id
        if mid in locked_ids or not compat.modelable(mid):
            continue
        modeled.append(mid)
        st, dur = compat.starts[mid], m.duration_slots
        lo, hi = int(st[0]), int(st[-1])
        if st.size == hi - lo + 1:
            sv = cm.NewIntVar(lo, hi, f"s_{mid}")
        else:
            sv = cm.NewIntVarFromDomain(cp_model.Domain.FromValues(st.tolist()), f"s_{mid}")
        pv = cm.NewBoolVar(f"p_{mid}")
        s[mid], p[mid] = sv, pv

        # delay = (start - earliest) when flown, 0 when dropped  -> exact match with score_plan
        lo_m = max(m.earliest, now)
        dl = cm.NewIntVar(0, hi - lo_m, f"dl_{mid}")
        cm.Add(dl == sv - lo_m).OnlyEnforceIf(pv)
        cm.Add(dl == 0).OnlyEnforceIf(pv.Not())
        obj_v += [pv, dl]
        obj_c += [gain(m, w), -w.delay]

        xs[mid], ys[mid] = [], []
        x_by_base, y_by_base = defaultdict(list), defaultdict(list)
        for aid in compat.aircraft[mid]:
            a = a_by[aid]
            xv = cm.NewBoolVar(f"x_{mid}_{aid}")
            xs[mid].append((aid, xv))
            x_by_base[a.base_id].append(xv)
            ac_iv[aid].append(cm.NewOptionalFixedSizeIntervalVar(sv, dur + a.turnaround_slots, xv, ""))
            if a.available_from > lo:
                cm.Add(sv >= a.available_from).OnlyEnforceIf(xv)
            if a.available_until < hi + dur:
                cm.Add(sv + dur <= a.available_until).OnlyEnforceIf(xv)
            if a.base_id in rw_bases:
                rw_iv[a.base_id].append(cm.NewOptionalFixedSizeIntervalVar(sv, 1, xv, ""))
            rc = risk_cost(m, a, w)
            if rc:
                obj_v.append(xv)
                obj_c.append(-rc)
        for cid in compat.crew[mid]:
            c = c_by[cid]
            yv = cm.NewBoolVar(f"y_{mid}_{cid}")
            ys[mid].append((cid, yv))
            y_by_base[c.base_id].append(yv)
            cr_iv[cid].append(cm.NewOptionalFixedSizeIntervalVar(sv, dur + rest, yv, ""))
            if c.rest_until > lo:
                cm.Add(sv >= c.rest_until).OnlyEnforceIf(yv)
            duty[cid].append((dur, yv))
        cm.Add(_sum([v for _, v in xs[mid]]) == pv)
        cm.Add(_sum([v for _, v in ys[mid]]) == pv)
        for b, xl in x_by_base.items():
            cm.Add(_sum(xl) == _sum(y_by_base[b]))

        # churn: reward keeping the briefed sortie exactly as it was
        r = ref.get(mid)
        if r is not None and w.churn and _has(st, r.start):
            xa = next((v for aid, v in xs[mid] if aid == r.aircraft_id), None)
            yc = next((v for cid, v in ys[mid] if cid == r.crew_id), None)
            if xa is not None and yc is not None:
                same = cm.NewBoolVar(f"same_{mid}")
                cm.AddImplication(same, xa)
                cm.AddImplication(same, yc)
                cm.Add(sv == r.start).OnlyEnforceIf(same)
                obj_v.append(same)
                obj_c.append(w.churn)

    # ---- fixed blocks: outages + locked sorties
    lk_ac, lk_cr = defaultdict(list), defaultdict(list)
    for a in locked:
        m = m_by[a.mission_id]
        lk_ac[a.aircraft_id].append((a.start, m.duration_slots + a_by[a.aircraft_id].turnaround_slots))
        lk_cr[a.crew_id].append((a.start, m.duration_slots + rest))

    def fixed(blocks):
        return [cm.NewFixedSizeIntervalVar(max(0, st_), ln, "") for st_, ln in blocks if st_ + ln > now]

    for aid, ivs in ac_iv.items():
        a = a_by[aid]
        fx = fixed(outage_blocks(a.outages, lk_ac[aid]) + lk_ac[aid])
        if len(ivs) + len(fx) > 1:
            cm.AddNoOverlap(ivs + fx)
    for cid, ivs in cr_iv.items():
        c = c_by[cid]
        fx = fixed(outage_blocks(c.outages, lk_cr[cid]) + lk_cr[cid])
        if len(ivs) + len(fx) > 1:
            cm.AddNoOverlap(ivs + fx)

    lk_take = defaultdict(list)
    for a in locked:
        if a.start >= now:
            lk_take[a_by[a.aircraft_id].base_id].append(a.start)
    for b in state.bases:
        ivs = rw_iv.get(b.id)
        if not ivs:
            continue
        fx = [cm.NewFixedSizeIntervalVar(max(0, o), e - o, "") for o, e in merge_windows(b.closures) if e > now]
        dem = [1] * len(ivs) + [b.runway_capacity] * len(fx)
        t_fx = [cm.NewFixedSizeIntervalVar(t, 1, "") for t in lk_take[b.id]]
        cm.AddCumulative(ivs + fx + t_fx, dem + [1] * len(t_fx), b.runway_capacity)

    for cid, lst in duty.items():
        left = compat.duty_left[cid]
        if sum(d for d, _ in lst) > left:
            cm.Add(_wsum([v for _, v in lst], [d for d, _ in lst]) <= left)

    if obj_v:
        cm.Maximize(_wsum(obj_v, obj_c))

    if hint is not None:
        hmap = {a.mission_id: a for a in hint.assignments}
        for mid in modeled:
            h = hmap.get(mid)
            cm.AddHint(p[mid], 1 if h else 0)
            for aid, v in xs[mid]:
                cm.AddHint(v, 1 if h and h.aircraft_id == aid else 0)
            for cid, v in ys[mid]:
                cm.AddHint(v, 1 if h and h.crew_id == cid else 0)
            if h and _has(compat.starts[mid], h.start):
                cm.AddHint(s[mid], h.start)

    return Built(cm, p, s, xs, ys, modeled)
