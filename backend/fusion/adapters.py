from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx


@dataclass(frozen=True, slots=True)
class Reading:
    source: str
    timestamp: str
    value: Any
    freshness_seconds: float            # age of the reading when collected
    confidence: float                   # 0..1
    status: str = "FRESH"
    kind: str = "generic"               # readings are only ever compared within the same kind
    key: str = ""                       # sector / aircraft id / crew id / zone id ...
    max_age_seconds: float = 120.0      # older than this = STALE


class Adapter(Protocol):
    name: str

    def read(self, state: dict[str, Any]) -> list[Reading]: ...


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _weather_at(values: list, now: int) -> int:
    return int(values[min(max(now, 0), len(values) - 1)]) if values else 0


class SimulatedWeatherAdapter:
    name = "simulated.weather.primary"

    def read(self, state: dict[str, Any]) -> list[Reading]:
        now = state.get("now", 0)
        return [Reading(self.name, now_iso(), {"sector": sector, "severity": _weather_at(values, now)}, 0, 0.96,
                        kind="weather", key=sector)
                for sector, values in state.get("weather", {}).items()]


class SimulatedWeatherSecondaryAdapter:
    """Second source intentionally disagrees on one sector so the conflict policy is visible."""
    name = "simulated.weather.secondary"

    def read(self, state: dict[str, Any]) -> list[Reading]:
        now = state.get("now", 0)
        out = []
        for sector, values in state.get("weather", {}).items():
            severity = _weather_at(values, now)
            if sector == "BRAVO":
                severity = max(0, severity - 1)
            out.append(Reading(self.name, now_iso(), {"sector": sector, "severity": severity}, 4, 0.82,
                               kind="weather", key=sector))
        return out


class SimulatedMaintenanceAdapter:
    name = "simulated.maintenance"

    def read(self, state: dict[str, Any]) -> list[Reading]:
        return [Reading(self.name, now_iso(),
                        {"aircraft_id": a["id"],
                         "status": "AVAILABLE" if not a.get("outages") else "SCHEDULED_OUTAGE"},
                        0, 0.97, kind="aircraft_status", key=a["id"])
                for a in state.get("aircraft", [])]


class SimulatedCrewAdapter:
    name = "simulated.crew"

    def read(self, state: dict[str, Any]) -> list[Reading]:
        return [Reading(self.name, now_iso(),
                        {"crew_id": c["id"], "duty_slots_used": c.get("duty_slots_used", 0),
                         "rest_until": c.get("rest_until", 0)},
                        0, 0.98, kind="crew_duty", key=c["id"])
                for c in state.get("crew", [])]


class SimulatedThreatAdapter:
    """Keyed by zone id, NOT sector, so a threat can never overwrite a weather reading."""
    name = "simulated.threat"

    def read(self, state: dict[str, Any]) -> list[Reading]:
        now = state.get("now", 0)
        return [Reading(self.name, now_iso(),
                        {"zone_id": z["id"], "sector": z["sector"], "severity": z["severity"]},
                        0, 0.91, kind="threat", key=z["id"])
                for z in state.get("threats", []) if z.get("start", 0) <= now < z.get("end", 0)]


class SimulatedLegacyRosterAdapter:
    """An old system still saying 'aircraft OK'. Stale + low confidence: it must lose to fresh data."""
    name = "simulated.legacy-roster"

    def __init__(self, seed: int = 0):
        self.seed = seed

    def read(self, state: dict[str, Any]) -> list[Reading]:
        aircraft = state.get("aircraft", [])
        if not aircraft:
            return []
        ac = aircraft[random.Random(self.seed).randrange(len(aircraft))]["id"]
        return [Reading(self.name, now_iso(), {"aircraft_id": ac, "status": "OK"}, 900, 0.55,
                        kind="aircraft_fault", key=ac, max_age_seconds=600)]


class SimulatedIncidentAdapter:
    """New information arriving mid-operation (simulated). Fresh incidents become engine events;
    the stale crew report is shown but must never be acted on."""
    name = "simulated.incident-feed"

    def __init__(self, seed: int = 0):
        self.seed = seed

    def read(self, state: dict[str, Any]) -> list[Reading]:
        rng = random.Random(self.seed)
        aircraft, crew = state.get("aircraft", []), state.get("crew", [])
        sectors = list(state.get("weather", {})) or ["ALPHA"]
        out: list[Reading] = []
        if aircraft:
            ac = aircraft[rng.randrange(len(aircraft))]["id"]
            out.append(Reading(self.name, now_iso(), {"aircraft_id": ac, "status": "OUT", "duration": None},
                               20, 0.90, kind="aircraft_fault", key=ac, max_age_seconds=600))
        if crew:
            cr = crew[rng.randrange(len(crew))]["id"]
            out.append(Reading(self.name, now_iso(), {"crew_id": cr, "status": "OUT", "duration": 24},
                               4000, 0.90, kind="crew_fault", key=cr, max_age_seconds=1800))
        sector = sectors[rng.randrange(len(sectors))]
        out.append(Reading(self.name, now_iso(), {"sector": sector, "severity": 5, "duration": 12},
                           15, 0.88, kind="weather_escalation", key=sector))
        return out


class OpenMeteoWeatherAdapter:
    """Optional public weather adapter. Disabled unless coordinates are configured.
    Returns generic weather observations, never operational/military data."""
    name = "open-meteo"

    def __init__(self, latitude: float, longitude: float, timeout: float = 5.0):
        self.latitude = latitude
        self.longitude = longitude
        self.timeout = timeout

    def read(self, state: dict[str, Any]) -> list[Reading]:
        params = {"latitude": self.latitude, "longitude": self.longitude,
                  "current": "temperature_2m,precipitation,wind_speed_10m,visibility,weather_code"}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            current = response.json().get("current", {})
        return [Reading(self.name, now_iso(), current, 0, 0.99, kind="weather_observation", key="open-meteo")]
