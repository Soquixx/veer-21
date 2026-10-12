"""Seeded scenario + disruption generator. generate(size, tightness, seed) is bit-for-bit
reproducible, so anyone can regenerate the exact benchmark from the seed.

Knobs
  size        S / M / L / XL            fleet, crew and mission counts
  tightness   ~0.6 relaxed .. 1.1 oversubscribed. Controls how tightly mission windows are
              packed into a surge period and how little slack each window has.
  trap_groups plants the classic "greedy strands two missions" structure on purpose.
All data is synthetic: fictional bases, generic aircraft classes."""
from __future__ import annotations

import math
import random
from collections import defaultdict

from ..domain.enums import PRIORITY_VALUE, AcType, EventType
from ..domain.models import (Aircraft, Base, Crew, Event, Mission, Plan, State,
                             ThreatZone)

SIZES: dict[str, dict] = {
    "S": dict(aircraft=10, missions=20, bases=2, horizon=96, crew_ratio=1.4),
    "M": dict(aircraft=25, missions=50, bases=3, horizon=96, crew_ratio=1.4),
    "L": dict(aircraft=50, missions=100, bases=4, horizon=144, crew_ratio=1.4),
    "XL": dict(aircraft=100, missions=250, bases=6, horizon=192, crew_ratio=1.4),
}
TYPE_MIX = [(AcType.FIGHTER, 0.35), (AcType.TRANSPORT, 0.25), (AcType.HELO, 0.20), (AcType.ISR, 0.20)]
TYPE_SPEC = {
    AcType.FIGHTER: dict(range=1500, turn=3, loads=["AA", "AG", "CAP"], risk_tol=3, dur=(4, 10)),
    AcType.TRANSPORT: dict(range=3000, turn=2, loads=[], risk_tol=1, dur=(6, 16)),
    AcType.HELO: dict(range=600, turn=2, loads=[], risk_tol=1, dur=(3, 8)),
    AcType.ISR: dict(range=2500, turn=3, loads=[], risk_tol=3, dur=(8, 20)),
}
SECTORS = ["ALPHA", "BRAVO", "CHARLIE", "DELTA"]


def _split(n: int) -> dict[AcType, int]:
    counts = {t: max(1, int(n * w)) for t, w in TYPE_MIX}
    diff, i, order = n - sum(counts.values()), 0, [t for t, _ in TYPE_MIX]
    while diff:
        t = order[i % len(order)]
        if diff > 0:
            counts[t] += 1
            diff -= 1
        elif counts[t] > 1:
            counts[t] -= 1
            diff += 1
        i += 1
    return counts


def generate(size: str = "M", tightness: float = 0.9, seed: int = 0, trap_groups: int = 0) -> State:
    cfg, rng = SIZES[size], random.Random(seed)
    H = cfg["horizon"]
    bases = [Base(id=f"BASE-{chr(65 + i)}") for i in range(cfg["bases"])]

    # ---- aircraft
    types = [t for t, n in _split(cfg["aircraft"]).items() for _ in range(n)]
    rng.shuffle(types)
    aircraft: list[Aircraft] = []
    for i, t in enumerate(types):
        spec = TYPE_SPEC[t]
        a = Aircraft(
            id=f"AC{i:03d}", ac_type=t, base_id=bases[i % len(bases)].id,
            weapon_loads=rng.sample(spec["loads"], 2) if spec["loads"] else [],
            range_km=int(spec["range"] * rng.uniform(0.8, 1.2)), turnaround_slots=spec["turn"],
            p_serviceable=round(rng.uniform(0.78, 0.98), 3), available_until=H)
        if rng.random() < 0.12:
            a.available_from = rng.randint(6, 30)
        if rng.random() < 0.10:
            s0 = rng.randint(10, H - 20)
            a.outages.append((s0, s0 + rng.randint(6, 16)))      # scheduled maintenance
        aircraft.append(a)
    n_at = defaultdict(int)
    for a in aircraft:
        n_at[a.base_id] += 1
    for b in bases:
        b.runway_capacity = 1 if n_at[b.id] <= 6 else 2

    # ---- crew (base-bound; sized per base/type so the world is flyable)
    by_bt: dict[tuple[str, AcType], int] = defaultdict(int)
    types_at: dict[str, list[AcType]] = defaultdict(list)
    for a in aircraft:
        by_bt[(a.base_id, a.ac_type)] += 1
        if a.ac_type not in types_at[a.base_id]:
            types_at[a.base_id].append(a.ac_type)
    crew: list[Crew] = []
    for (b, t), n in sorted(by_bt.items()):
        others = [x for x in types_at[b] if x != t]
        for _ in range(max(2, math.ceil(n * cfg["crew_ratio"]))):
            ratings = [t] + ([rng.choice(others)] if others and rng.random() < 0.3 else [])
            crew.append(Crew(id=f"CR{len(crew):03d}", base_id=b, ratings=ratings,
                             duty_slots_used=rng.randint(0, 16),
                             rest_until=rng.randint(4, 20) if rng.random() < 0.10 else 0))

    # ---- missions: tightness = demand / aircraft-capacity inside the surge window
    drafts = []
    for i in range(cfg["missions"]):
        t = rng.choices([t for t, _ in TYPE_MIX], [w for _, w in TYPE_MIX])[0]
        spec = TYPE_SPEC[t]
        dur = max(2, round(rng.randint(*spec["dur"]) * 1.15))
        drafts.append((i, t, spec, rng.choices([1, 2, 3, 4, 5], [10, 20, 35, 25, 10])[0], dur,
                       max(2, round(dur * (1.7 - tightness)))))
    demand = sum(d[4] + d[2]["turn"] for d in drafts)
    W = int(min(H - 24, max(16, demand / (len(aircraft) * tightness))))
    off = rng.randint(0, max(0, H - W - 24))
    missions: list[Mission] = []
    for i, t, spec, pr, dur, slack in drafts:
        earliest = max(0, min(off + rng.randint(0, max(0, W - dur)), H - dur - slack))
        missions.append(Mission(
            id=f"M{i:03d}", priority=pr, value=round(PRIORITY_VALUE[pr] * rng.uniform(0.9, 1.1)),
            ac_type=t, earliest=earliest, latest=earliest + dur + slack, duration_slots=dur,
            sector=rng.choice(SECTORS), distance_km=rng.randint(100, int(spec["range"] * 0.45)),
            weapon_load=rng.choice(spec["loads"]) if spec["loads"] and rng.random() < 0.7 else None,
            weather_limit=2 if rng.random() < 0.35 else 4, risk_tolerance=spec["risk_tol"]))

    # ---- weather cells + threat zones, placed inside the surge so they actually matter
    weather = {s: [0] * H for s in SECTORS}
    for s in SECTORS:
        for _ in range(rng.choice([0, 1, 1, 2])):
            a0, ln, sev = off + rng.randint(0, W), rng.randint(8, 20), rng.randint(2, 4)
            for t in range(a0, min(H, a0 + ln)):
                weather[s][t] = max(weather[s][t], sev)
    threats = []
    for i in range(rng.choice([0, 1, 2])):
        a0 = min(off + rng.randint(0, W), H - 24)
        threats.append(ThreatZone(f"TH{i}", rng.choice(SECTORS), a0, a0 + rng.randint(10, 24), rng.randint(2, 4)))

    state = State(horizon=H, bases=bases, aircraft=aircraft, crew=crew, missions=missions,
                  threats=threats, weather=weather)
    _plant_traps(state, rng, trap_groups)
    return state


def _plant_traps(state: State, rng: random.Random, groups: int) -> None:
    """Crew X (rated on both types, rested) is the greedy favourite for P1 mission A, which
    strands B and C that only X can fly. Optimal: A -> crew Y, B and C -> X (3 missions, not 1).
    Trap aircraft have a 100 km range and trap missions a 40 km radius, so no regular mission
    (min radius 100 km) can borrow them and distort the structure."""
    H = state.horizon
    for g in range(groups):
        base, sec = f"TB{g}", f"TRAP{g}"
        t0 = rng.randint(4, H - 30)
        state.bases.append(Base(id=base, runway_capacity=2))
        state.aircraft.append(Aircraft(f"TAC{g}F", AcType.FIGHTER, base, [f"TL{g}A"], 100, 3, 0.95, 0, H))
        state.aircraft.append(Aircraft(f"TAC{g}I", AcType.ISR, base, [f"TL{g}I"], 100, 3, 0.95, 0, H))
        state.crew.append(Crew(f"TCR{g}X", base, [AcType.FIGHTER, AcType.ISR], duty_slots_used=0))
        state.crew.append(Crew(f"TCR{g}Y", base, [AcType.FIGHTER], duty_slots_used=8))
        mk = lambda sfx, pr, t, e, d, load: Mission(
            f"TRAP{g}-{sfx}", pr, PRIORITY_VALUE[pr], t, e, e + d + 2, d, sec, 40, load)
        state.missions += [mk("A", 1, AcType.FIGHTER, t0, 14, f"TL{g}A"),
                           mk("B", 2, AcType.ISR, t0, 5, f"TL{g}I"),
                           mk("C", 2, AcType.ISR, t0 + 8, 5, f"TL{g}I")]


# -------------------------------------------------------------- disruptions
EVENT_KINDS = ("aircraft_out", "crew_out", "weather", "threat", "runway", "combined")


def make_event(state: State, plan: Plan, kind: str = "aircraft_out", seed: int = 0) -> list[Event]:
    """Disruption aimed where it hurts: at the busiest resource / sector after the event time."""
    rng = random.Random(seed * 7919 + 13)
    future = sorted(a.start for a in plan.assignments if a.start >= state.now)
    t = future[len(future) // 4] if future else state.now
    after = [a for a in plan.assignments if a.start >= t]
    m_by = {m.id: m for m in state.missions}
    base_of = {a.id: a.base_id for a in state.aircraft}

    def busiest(key) -> str:
        cnt: dict[str, int] = defaultdict(int)
        for a in after:
            cnt[key(a)] += 1
        top = max(cnt.values())
        return rng.choice(sorted(k for k, v in cnt.items() if v == top))

    ev: list[Event] = []
    if kind in ("aircraft_out", "combined"):
        ev.append(Event(f"E{seed}-AC", EventType.AIRCRAFT_OUT, t, target_id=busiest(lambda a: a.aircraft_id)))
    if kind in ("crew_out", "combined"):
        ev.append(Event(f"E{seed}-CR", EventType.CREW_OUT, t, target_id=busiest(lambda a: a.crew_id), duration=24))
    if kind in ("weather", "combined"):
        ev.append(Event(f"E{seed}-WX", EventType.WEATHER, t, sector=busiest(lambda a: m_by[a.mission_id].sector),
                        duration=12, severity=5))
    if kind == "threat":
        ev.append(Event(f"E{seed}-TH", EventType.THREAT_POPUP, t, sector=busiest(lambda a: m_by[a.mission_id].sector),
                        duration=16, severity=4))
    if kind == "runway":
        ev.append(Event(f"E{seed}-RW", EventType.RUNWAY_CLOSED, t, target_id=busiest(lambda a: base_of[a.aircraft_id]),
                        duration=8))
    if not ev:
        raise ValueError(f"unknown event kind {kind!r}; choose from {EVENT_KINDS}")
    return ev
