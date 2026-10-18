from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from typing import Any

from .adapters import Adapter, Reading

POLICY = "stale readings lose to fresh ones -> highest confidence -> most recent"


def is_stale(r: Reading) -> bool:
    return r.status == "STALE" or r.freshness_seconds > r.max_age_seconds


def _key_of(r: Reading) -> str:
    if r.key:
        return r.key
    v = r.value if isinstance(r.value, dict) else {}
    return str(v.get("sector") or v.get("aircraft_id") or v.get("crew_id") or v.get("zone_id") or r.source)


class FusionEngine:
    """Merges readings from several systems into one picture with provenance.
    Readings are only ever compared within the same (kind, key)."""

    def __init__(self, adapters: list[Adapter]):
        self.adapters = adapters

    def collect(self, state: dict[str, Any]) -> tuple[list[Reading], list[dict]]:
        readings: list[Reading] = []
        errors: list[dict] = []
        for adapter in self.adapters:
            try:
                readings.extend(adapter.read(state))
            except Exception as exc:                    # one broken feed must not blind the whole picture
                errors.append({"adapter": getattr(adapter, "name", type(adapter).__name__),
                               "error": f"{type(exc).__name__}: {exc}"})
        return readings, errors

    @staticmethod
    def _choose(readings: list[Reading]) -> tuple[Reading, str]:
        fresh = [r for r in readings if not is_stale(r)]
        pool = fresh or readings
        winner = sorted(pool, key=lambda r: (r.confidence, r.timestamp), reverse=True)[0]
        if len(readings) == 1:
            rule = "single source"
        elif not fresh:
            rule = "all sources stale: most trusted kept, flagged STALE"
        elif len(fresh) < len(readings) and len(fresh) == 1:
            rule = "stale readings discarded"
        elif len({r.confidence for r in fresh}) > 1:
            rule = "highest confidence among fresh readings"
        else:
            rule = "most recent among fresh readings"
        return winner, rule

    def fuse(self, state: dict[str, Any]) -> dict[str, Any]:
        readings, errors = self.collect(state)
        groups: dict[tuple[str, str], list[Reading]] = defaultdict(list)
        for r in readings:
            groups[(r.kind, _key_of(r))].append(r)

        resolved = []
        for (kind, key), rs in sorted(groups.items()):
            chosen, rule = self._choose(rs)
            values = {json.dumps(r.value, sort_keys=True, default=str) for r in rs}
            resolved.append({
                "kind": kind,
                "key": key,
                "status": "STALE" if is_stale(chosen) else "FRESH",
                "conflict": len(values) > 1,
                "chosen": asdict(chosen),
                "candidates": [{**asdict(r), "stale": is_stale(r)} for r in rs],
                "resolution_rule": rule,
                "policy": POLICY,
            })
        return {"readings": [asdict(r) for r in readings], "resolved": resolved,
                "adapter_count": len(self.adapters), "adapter_errors": errors}

    @staticmethod
    def to_events(result: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
        """Engine Event dicts from FRESH incident readings only. Stale data is displayed, never acted on."""
        now = int(state.get("now", 0))
        aircraft = {a["id"] for a in state.get("aircraft", [])}
        crew = {c["id"] for c in state.get("crew", [])}
        events: list[dict[str, Any]] = []
        for item in result["resolved"]:
            if item["status"] != "FRESH":
                continue
            v, kind, key = item["chosen"]["value"], item["kind"], item["key"]
            if kind == "aircraft_fault" and v.get("status") == "OUT" and key in aircraft:
                events.append({"id": f"F-AC-{key}", "type": "AIRCRAFT_OUT", "time": now,
                               "target_id": key, "duration": v.get("duration")})
            elif kind == "crew_fault" and v.get("status") == "OUT" and key in crew:
                events.append({"id": f"F-CR-{key}", "type": "CREW_OUT", "time": now,
                               "target_id": key, "duration": v.get("duration")})
            elif kind == "weather_escalation" and int(v.get("severity", 0)) >= 3:
                events.append({"id": f"F-WX-{key}", "type": "WEATHER", "time": now, "sector": key,
                               "duration": v.get("duration"), "severity": int(v["severity"])})
        return events
