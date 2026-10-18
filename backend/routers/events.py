from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from engine import service
from ..db.models import EventRecord, Scenario
from ..db.session import get_db
from ..deps import engine_call
from ..schemas import Events
from ..security import require_roles
from .scenarios import load, need_plan

router = APIRouter(prefix="/scenarios/{scenario_id}/events", tags=["events"])


@router.post("/suggest")
def suggest_event(scenario_id: str, kind: str = "combined", seed: int = 0, db: Session = Depends(get_db),
                  _=Depends(require_roles("planner", "approver"))):
    """A realistic disruption aimed at the busiest resource of the CURRENT plan."""
    _, v = load(db, scenario_id)
    plan = need_plan(db, v)                       # 409 if there is no plan (no fixture fallback)
    return engine_call(service.suggest_events, v.state_json, plan.plan_json, kind, seed)


@router.post("")
def record_events(scenario_id: str, events: Events, db: Session = Depends(get_db),
                  _=Depends(require_roles("planner", "approver"))):
    if not db.get(Scenario, scenario_id):
        raise HTTPException(404, "Scenario not found")
    rows = []
    for event in events:
        row = EventRecord(id=uuid4().hex, scenario_id=scenario_id, event_json=event, time=int(event["time"]))
        db.add(row)
        rows.append(row)
    db.commit()
    return [{"id": r.id, "event": r.event_json} for r in rows]
