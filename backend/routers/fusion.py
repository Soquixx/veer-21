from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db.models import Scenario, ScenarioVersion
from ..db.session import get_db
from ..fusion.adapters import (OpenMeteoWeatherAdapter, SimulatedCrewAdapter, SimulatedIncidentAdapter,
                               SimulatedLegacyRosterAdapter, SimulatedMaintenanceAdapter,
                               SimulatedThreatAdapter, SimulatedWeatherAdapter,
                               SimulatedWeatherSecondaryAdapter)
from ..fusion.fuser import FusionEngine
from ..security import require_roles
from ..settings import settings

router = APIRouter(tags=["data-fusion"])


def _engine(seed: int) -> FusionEngine:
    adapters = [SimulatedWeatherAdapter(), SimulatedWeatherSecondaryAdapter(), SimulatedMaintenanceAdapter(),
                SimulatedCrewAdapter(), SimulatedThreatAdapter(), SimulatedLegacyRosterAdapter(seed),
                SimulatedIncidentAdapter(seed)]
    if settings.weather_provider == "open-meteo" and settings.open_meteo_lat is not None \
            and settings.open_meteo_lon is not None:
        adapters.append(OpenMeteoWeatherAdapter(settings.open_meteo_lat, settings.open_meteo_lon))
    return FusionEngine(adapters)


def _current(db: Session, scenario_id: str | None) -> tuple[Scenario, ScenarioVersion]:
    s = db.get(Scenario, scenario_id) if scenario_id else \
        db.query(Scenario).order_by(Scenario.created_at.desc()).first()
    if not s or not s.current_version_id:
        raise HTTPException(404, "No scenario available")
    return s, db.get(ScenarioVersion, s.current_version_id)


@router.get("/provenance")
@router.get("/fusion/provenance")
def provenance(scenario_id: str | None = None, seed: int = 0, db: Session = Depends(get_db),
               _=Depends(require_roles("viewer", "planner", "approver"))):
    """Fused picture with freshness, confidence, conflicts and the rule that decided each one."""
    s, v = _current(db, scenario_id)
    result = _engine(seed).fuse(v.state_json)
    return {**result, "scenario_id": s.id, "scenario_version_id": v.id, "mode": "simulated"}


@router.post("/fusion/events")
def fusion_events(scenario_id: str | None = None, seed: int = 0, db: Session = Depends(get_db),
                  _=Depends(require_roles("planner", "approver"))):
    """Engine events derived from FRESH fused incident readings (stale ones are reported, not used).
    Feed the returned events to POST /api/scenarios/{id}/impact and /replan."""
    s, v = _current(db, scenario_id)
    eng = _engine(seed)
    result = eng.fuse(v.state_json)
    return {"events": eng.to_events(result, v.state_json), "resolved": result["resolved"],
            "scenario_id": s.id, "scenario_version_id": v.id, "mode": "simulated"}
