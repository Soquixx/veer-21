from __future__ import annotations

from enum import Enum, IntEnum


class Priority(IntEnum):
    P1 = 1
    P2 = 2
    P3 = 3
    P4 = 4
    P5 = 5


# Mission value by priority. Integer so the CP-SAT objective stays exact.
PRIORITY_VALUE: dict[int, int] = {1: 100, 2: 60, 3: 35, 4: 20, 5: 10}


class AcType(str, Enum):
    """Generic aircraft classes (deliberately fictional, no real platforms)."""
    FIGHTER = "FIGHTER-A"
    TRANSPORT = "TRANSPORT-B"
    HELO = "HELO-C"
    ISR = "ISR-D"


class EventType(str, Enum):
    AIRCRAFT_OUT = "AIRCRAFT_OUT"
    CREW_OUT = "CREW_OUT"
    WEATHER = "WEATHER"
    THREAT_POPUP = "THREAT_POPUP"
    RUNWAY_CLOSED = "RUNWAY_CLOSED"
    PRIORITY_CHANGE = "PRIORITY_CHANGE"
    NEW_MISSION = "NEW_MISSION"


class ViolationKind(str, Enum):
    UNKNOWN_ENTITY = "UNKNOWN_ENTITY"
    DUPLICATE_MISSION = "DUPLICATE_MISSION"
    AIRCRAFT_TYPE = "AIRCRAFT_TYPE"
    WEAPON_LOAD = "WEAPON_LOAD"
    RANGE = "RANGE"
    CREW_RATING = "CREW_RATING"
    BASE_MISMATCH = "BASE_MISMATCH"
    TIME_WINDOW = "TIME_WINDOW"
    AIRCRAFT_WINDOW = "AIRCRAFT_WINDOW"
    AIRCRAFT_OUTAGE = "AIRCRAFT_OUTAGE"
    AIRCRAFT_OVERLAP = "AIRCRAFT_OVERLAP"
    CREW_REST = "CREW_REST"
    CREW_OUTAGE = "CREW_OUTAGE"
    CREW_OVERLAP = "CREW_OVERLAP"
    CREW_DUTY = "CREW_DUTY"
    WEATHER = "WEATHER"
    THREAT = "THREAT"
    RUNWAY = "RUNWAY"
