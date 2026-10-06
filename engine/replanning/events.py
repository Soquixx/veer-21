"""Apply disruption events to an operational state (pure: returns a modified copy)."""
from __future__ import annotations

import copy
from typing import Iterable

from ..domain.enums import PRIORITY_VALUE, EventType
from ..domain.models import Event, Mission, State, ThreatZone, by_id, from_dict


def _apply(s: State, ev: Event) -> None:
    H = s.horizon
    end = H + 64 if ev.duration is None else ev.time + ev.duration
    s.now = max(s.now, ev.time)
    t = ev.type
    if t == EventType.AIRCRAFT_OUT:
        by_id(s.aircraft)[ev.target_id].outages.append((ev.time, end))
    elif t == EventType.CREW_OUT:
        by_id(s.crew)[ev.target_id].outages.append((ev.time, end))
    elif t == EventType.RUNWAY_CLOSED:
        by_id(s.bases)[ev.target_id].closures.append((ev.time, end))
    elif t == EventType.WEATHER:
        w = s.weather.setdefault(ev.sector, [0] * H)
        for i in range(max(0, ev.time), min(H, end)):
            w[i] = max(w[i], ev.severity)
    elif t == EventType.THREAT_POPUP:
        s.threats.append(ThreatZone(ev.id, ev.sector, ev.time, end, ev.severity))
    elif t == EventType.PRIORITY_CHANGE:
        m = by_id(s.missions)[ev.target_id]
        m.priority = int(ev.payload["priority"])
        m.value = PRIORITY_VALUE[m.priority]
    elif t == EventType.NEW_MISSION:
        s.missions.append(from_dict(Mission, ev.payload))
    else:
        raise ValueError(f"unsupported event type {t}")


def apply_events(state: State, events: Iterable[Event]) -> State:
    s = copy.deepcopy(state)
    for ev in sorted(events, key=lambda e: e.time):
        _apply(s, ev)
    return s


def apply_event(state: State, event: Event) -> State:
    return apply_events(state, [event])
