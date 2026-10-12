"""Plain slotted dataclasses: fast in the hot loops, and FastAPI can use them
directly as request/response models. Time is discrete: one slot = 15 minutes."""
from __future__ import annotations

import types
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Union, get_args, get_origin, get_type_hints

from .enums import AcType, EventType

Window = tuple[int, int]  # [start, end) in slots


@dataclass(slots=True)
class Base:
    id: str
    runway_capacity: int = 1                    # takeoffs per slot
    closures: list[Window] = field(default_factory=list)


@dataclass(slots=True)
class Aircraft:
    id: str
    ac_type: AcType
    base_id: str
    weapon_loads: list[str] = field(default_factory=list)
    range_km: int = 1500
    turnaround_slots: int = 2
    p_serviceable: float = 0.95
    available_from: int = 0
    available_until: int = 10_000
    outages: list[Window] = field(default_factory=list)


@dataclass(slots=True)
class Crew:
    id: str
    base_id: str
    ratings: list[AcType]
    duty_slots_used: int = 0
    max_duty_slots: int = 48
    rest_until: int = 0
    outages: list[Window] = field(default_factory=list)


@dataclass(slots=True)
class Mission:
    id: str
    priority: int
    value: int
    ac_type: AcType
    earliest: int
    latest: int                                 # latest END slot
    duration_slots: int
    sector: str
    distance_km: int = 0
    weapon_load: str | None = None
    weather_limit: int = 4                      # severity above this blocks the flight
    risk_tolerance: int = 3                     # threat severity above this blocks it


@dataclass(slots=True)
class ThreatZone:
    id: str
    sector: str
    start: int
    end: int
    severity: int


@dataclass(slots=True)
class State:
    horizon: int
    bases: list[Base]
    aircraft: list[Aircraft]
    crew: list[Crew]
    missions: list[Mission]
    threats: list[ThreatZone] = field(default_factory=list)
    weather: dict[str, list[int]] = field(default_factory=dict)   # sector -> severity/slot
    now: int = 0
    crew_rest_slots: int = 2
    slot_minutes: int = 15


@dataclass(slots=True)
class Assignment:
    mission_id: str
    aircraft_id: str
    crew_id: str
    start: int
    locked: bool = False


@dataclass(slots=True)
class Violation:
    kind: str
    mission_id: str | None
    detail: str


@dataclass(slots=True)
class Plan:
    assignments: list[Assignment] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    score: float = 0.0
    value: int = 0
    violations: list[Violation] = field(default_factory=list)
    status: str = ""
    solve_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Event:
    id: str
    type: EventType
    time: int
    target_id: str | None = None
    sector: str | None = None
    duration: int | None = None                 # None = until end of horizon
    severity: int = 0
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlanMetrics:
    value: int
    value_retained: float
    missions: int
    sorties_changed: int
    stability: float
    solve_ms: float
    violations: int
    robustness: float | None = None


# ---------------------------------------------------------------- helpers
def by_id(items) -> dict[str, Any]:
    return {i.id: i for i in items}


def to_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)


@lru_cache(maxsize=None)
def _hints(tp: type) -> dict[str, Any]:
    return get_type_hints(tp)


def from_dict(tp: Any, data: Any) -> Any:
    """Rebuild any model above from JSON-style data, e.g. from_dict(State, payload)."""
    if data is None:
        return None
    origin = get_origin(tp)
    if is_dataclass(tp):
        hints = _hints(tp)
        return tp(**{k: from_dict(hints[k], v) for k, v in data.items() if k in hints})
    if origin is list:
        (arg,) = get_args(tp)
        return [from_dict(arg, v) for v in data]
    if origin is tuple:
        return tuple(data)
    if origin is dict:
        _, vt = get_args(tp)
        return {k: from_dict(vt, v) for k, v in data.items()}
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        return from_dict(args[0], data)
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(data)
    return data
