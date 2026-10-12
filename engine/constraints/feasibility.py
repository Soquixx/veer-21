"""Single source of truth for 'what is allowed'.

* build_compat  - prunes the search space BEFORE any solver runs (compatibility, hazard-free
                  start slots, duty budgets). Shared by the greedy baseline and CP-SAT.
* validate      - independent checker that re-derives every rule from the raw state. It is the
                  referee for both the solver and the baseline; any disagreement is a bug.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

from ..domain.enums import ViolationKind as K
from ..domain.models import Assignment, Mission, Plan, State, Violation, by_id

_EMPTY = np.empty(0, dtype=np.int64)


# ------------------------------------------------------------------ hazards
@dataclass(slots=True)
class Hazards:
    horizon: int
    weather: dict[str, np.ndarray]
    threat: dict[str, np.ndarray]
    cache: dict = field(default_factory=dict)

    def cum_bad(self, sector: str, wl: int, rt: int) -> np.ndarray:
        """Prefix sums of 'blocked' slots for a (sector, weather_limit, risk_tolerance) class."""
        key = (sector, wl, rt)
        cs = self.cache.get(key)
        if cs is None:
            zero = np.zeros(self.horizon, np.int8)
            bad = (self.weather.get(sector, zero) > wl) | (self.threat.get(sector, zero) > rt)
            cs = np.concatenate(([0], np.cumsum(bad, dtype=np.int32)))
            self.cache[key] = cs
        return cs


def build_hazards(state: State) -> Hazards:
    H = state.horizon
    weather: dict[str, np.ndarray] = {}
    for sec, vals in state.weather.items():
        arr = np.zeros(H, np.int8)
        n = min(H, len(vals))
        arr[:n] = vals[:n]
        weather[sec] = arr
    threat: dict[str, np.ndarray] = {}
    for z in state.threats:
        arr = threat.setdefault(z.sector, np.zeros(H, np.int8))
        s, e = max(0, z.start), min(H, z.end)
        if e > s:
            arr[s:e] = np.maximum(arr[s:e], z.severity)
    return Hazards(H, weather, threat)


def feasible_starts(m: Mission, hz: Hazards, now: int) -> np.ndarray:
    """Start slots where the whole flight is inside the window and hazard-free."""
    H = hz.horizon
    lo = max(m.earliest, now, 0)
    hi = min(m.latest - m.duration_slots, H - 1)
    if hi < lo:
        return _EMPTY
    ts = np.arange(lo, hi + 1)
    cs = hz.cum_bad(m.sector, m.weather_limit, m.risk_tolerance)
    end = np.minimum(ts + m.duration_slots, H)
    return ts[(cs[end] - cs[ts]) == 0]


# ------------------------------------------------------------ compatibility
@dataclass(slots=True)
class Compat:
    hz: Hazards
    starts: dict[str, np.ndarray]
    aircraft: dict[str, list[str]]
    crew: dict[str, list[str]]
    duty_left: dict[str, int]

    def modelable(self, mid: str) -> bool:
        return mid in self.starts and self.starts[mid].size > 0 \
            and bool(self.aircraft[mid]) and bool(self.crew[mid])


def build_compat(state: State, locked: Sequence[Assignment] = (), *,
                 only: Iterable[str] | None = None, hz: Hazards | None = None,
                 exclude_aircraft: Iterable[str] = (),
                 exclude_crew: Iterable[str] = ()) -> Compat:
    hz = hz or build_hazards(state)
    now = state.now
    m_by = by_id(state.missions)
    ex_a, ex_c = set(exclude_aircraft), set(exclude_crew)
    only_set = None if only is None else set(only)
    locked_ids = {a.mission_id for a in locked}

    duty_left = {c.id: c.max_duty_slots - c.duty_slots_used for c in state.crew}
    for a in locked:
        duty_left[a.crew_id] -= m_by[a.mission_id].duration_slots

    ac_by_type, cr_by_type = defaultdict(list), defaultdict(list)
    for a in state.aircraft:
        if a.id not in ex_a:
            ac_by_type[a.ac_type].append(a)
    for c in state.crew:
        if c.id not in ex_c:
            for r in c.ratings:
                cr_by_type[r].append(c)

    starts, aircraft, crew = {}, {}, {}
    for m in state.missions:
        if m.id in locked_ids or (only_set is not None and m.id not in only_set):
            continue
        st = feasible_starts(m, hz, now)
        starts[m.id] = st
        aircraft[m.id], crew[m.id] = [], []
        if st.size == 0:
            continue
        dur, s0, s1 = m.duration_slots, int(st[0]), int(st[-1])

        acs = []
        for a in ac_by_type[m.ac_type]:
            if m.weapon_load and m.weapon_load not in a.weapon_loads:
                continue
            if 2 * m.distance_km > a.range_km:
                continue
            if not (a.available_from <= s0 and s1 + dur <= a.available_until):
                if not ((st >= a.available_from) & (st + dur <= a.available_until)).any():
                    continue
            acs.append(a)
        crs = [c for c in cr_by_type[m.ac_type]
               if duty_left[c.id] >= dur and c.rest_until <= s1]
        bases = {a.base_id for a in acs} & {c.base_id for c in crs}   # crews are base-bound
        aircraft[m.id] = [a.id for a in acs if a.base_id in bases]
        crew[m.id] = [c.id for c in crs if c.base_id in bases]
    return Compat(hz, starts, aircraft, crew, duty_left)


def explain_unassigned(mid: str, compat: Compat) -> str:
    """Human-readable reason a mission is not in the plan (explainability, cheap)."""
    if mid not in compat.starts:
        return "not considered in this run"
    if compat.starts[mid].size == 0:
        return "no hazard-free start slot inside the mission window (weather / threat / timing)"
    if not compat.aircraft[mid]:
        return "no compatible aircraft (type, weapon load, range, availability or crew base)"
    if not compat.crew[mid]:
        return "no rated crew with enough duty hours / rest at an eligible base"
    return "capacity: every compatible aircraft or crew is committed to higher-value work in this window"


def merge_windows(windows) -> list[tuple[int, int]]:
    """Union of [start, end) windows. Overlapping FIXED intervals in one NoOverlap/Cumulative
    constraint make a CP-SAT model infeasible, so they must be merged first."""
    out: list[list[int]] = []
    for s_, e_ in sorted(windows):
        if out and s_ <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e_)
        else:
            out.append([s_, e_])
    return [(s_, e_) for s_, e_ in out]


def outage_blocks(outages, locked_blocks) -> list[tuple[int, int]]:
    """Fixed (start, length) blocks for outages.
    1. overlapping outages (e.g. scheduled maintenance + a new failure) are merged;
    2. an aircraft/crew already committed to a locked (airborne) sortie finishes it first, so an
       outage that begins mid-sortie starts when that sortie ends."""
    out = []
    locks = sorted(locked_blocks)
    for o, e in merge_windows(outages):
        for ls, ln in locks:
            if ls < e and o < ls + ln:
                o = max(o, ls + ln)
        if e > o:
            out.append((o, e - o))
    return out


# --------------------------------------------------------------- validation
def _overlaps(w: Iterable[tuple[int, int]], s: int, length: int) -> bool:
    return any(s < e and o < s + length for o, e in w)


def validate(plan: Plan, state: State, *, since: int | None = None) -> list[Violation]:
    """Re-derive every rule from the raw state. Time-dependent rules (outages, hazards,
    runway) are only checked for sorties starting at/after `since` (default: state.now);
    sorties already flown are history."""
    since = state.now if since is None else since
    out: list[Violation] = []

    def add(kind: K, mid: str | None, detail: str) -> None:
        out.append(Violation(kind.value, mid, detail))

    m_by, a_by, c_by, b_by = (by_id(x) for x in (state.missions, state.aircraft, state.crew, state.bases))
    hz = build_hazards(state)
    rest = state.crew_rest_slots
    seen: set[str] = set()
    per_ac, per_cr = defaultdict(list), defaultdict(list)
    duty: Counter = Counter()
    takeoffs: dict[tuple[str, int], list[str]] = defaultdict(list)

    for asg in plan.assignments:
        m, a, c = m_by.get(asg.mission_id), a_by.get(asg.aircraft_id), c_by.get(asg.crew_id)
        if m is None or a is None or c is None:
            add(K.UNKNOWN_ENTITY, asg.mission_id, f"unknown id in {asg}")
            continue
        if m.id in seen:
            add(K.DUPLICATE_MISSION, m.id, "mission assigned more than once")
        seen.add(m.id)
        s, dur = asg.start, m.duration_slots

        if a.ac_type != m.ac_type:
            add(K.AIRCRAFT_TYPE, m.id, f"{a.id} is {a.ac_type.value}, needs {m.ac_type.value}")
        if m.weapon_load and m.weapon_load not in a.weapon_loads:
            add(K.WEAPON_LOAD, m.id, f"{a.id} cannot carry {m.weapon_load}")
        if 2 * m.distance_km > a.range_km:
            add(K.RANGE, m.id, f"round trip {2 * m.distance_km} km > range {a.range_km} km")
        if m.ac_type not in c.ratings:
            add(K.CREW_RATING, m.id, f"{c.id} not rated on {m.ac_type.value}")
        if a.base_id != c.base_id:
            add(K.BASE_MISMATCH, m.id, f"{a.id}@{a.base_id} vs {c.id}@{c.base_id}")
        if s < m.earliest or s + dur > m.latest:
            add(K.TIME_WINDOW, m.id, f"[{s},{s + dur}) outside [{m.earliest},{m.latest})")
        if s < a.available_from or s + dur > a.available_until:
            add(K.AIRCRAFT_WINDOW, m.id, f"{a.id} not available over [{s},{s + dur})")
        if s < c.rest_until:
            add(K.CREW_REST, m.id, f"{c.id} resting until {c.rest_until}")

        a_len, c_len = dur + a.turnaround_slots, dur + rest
        per_ac[a.id].append((s, a_len, m.id))
        per_cr[c.id].append((s, c_len, m.id))
        duty[c.id] += dur

        if s >= since:
            if _overlaps(a.outages, s, a_len):
                add(K.AIRCRAFT_OUTAGE, m.id, f"{a.id} unavailable during sortie")
            if _overlaps(c.outages, s, c_len):
                add(K.CREW_OUTAGE, m.id, f"{c.id} unavailable during sortie")
            w, t = hz.weather.get(m.sector), hz.threat.get(m.sector)
            if w is not None and w[s:s + dur].size and int(w[s:s + dur].max()) > m.weather_limit:
                add(K.WEATHER, m.id, f"weather above limit {m.weather_limit} in {m.sector}")
            if t is not None and t[s:s + dur].size and int(t[s:s + dur].max()) > m.risk_tolerance:
                add(K.THREAT, m.id, f"threat above tolerance {m.risk_tolerance} in {m.sector}")
            takeoffs[(a.base_id, s)].append(m.id)

    for kind, table in ((K.AIRCRAFT_OVERLAP, per_ac), (K.CREW_OVERLAP, per_cr)):
        for rid, lst in table.items():
            lst.sort()
            for (s0, l0, _), (s1, _, mid1) in zip(lst, lst[1:]):
                if s1 < s0 + l0:
                    add(kind, mid1, f"{rid} busy until {s0 + l0}, next sortie starts {s1}")

    for cid, used in duty.items():
        c = c_by[cid]
        if c.duty_slots_used + used > c.max_duty_slots:
            add(K.CREW_DUTY, None, f"{cid} duty {c.duty_slots_used + used} > {c.max_duty_slots}")

    for (bid, t), mids in takeoffs.items():
        b = b_by[bid]
        cap = 0 if any(s <= t < e for s, e in b.closures) else b.runway_capacity
        if len(mids) > cap:
            for mid in mids:
                add(K.RUNWAY, mid, f"{bid} takeoff slot {t}: {len(mids)} > capacity {cap}")
    return out
