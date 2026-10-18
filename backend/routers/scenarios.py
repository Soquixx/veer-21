from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from engine import service
from ..db.models import Decision, EventRecord, PlanRecord, Scenario, ScenarioVersion, User
from ..db.session import get_db
from ..deps import engine_call, get_jobs
from ..schemas import (ScenarioCreateRequest, ScenarioImpactRequest, ScenarioPlanRequest,
                       ScenarioReplanRequest)
from ..security import require_roles

router = APIRouter(prefix="/scenarios", tags=["scenarios"])
ANY = require_roles("viewer", "planner", "approver")
PLANNER = require_roles("planner", "approver")


# ------------------------------------------------------------------ helpers
def load(db: Session, scenario_id: str) -> tuple[Scenario, ScenarioVersion]:
    s = db.get(Scenario, scenario_id)
    if s is None or not s.current_version_id:
        raise HTTPException(404, "Scenario not found")
    v = db.get(ScenarioVersion, s.current_version_id)
    if v is None:
        raise HTTPException(500, "Scenario points at a missing version")
    return s, v


def current_plan(db: Session, version_id: str) -> PlanRecord | None:
    return db.scalars(select(PlanRecord).where(PlanRecord.scenario_version_id == version_id)
                      .order_by(PlanRecord.created_at.desc())).first()


def need_plan(db: Session, version: ScenarioVersion) -> PlanRecord:
    plan = current_plan(db, version.id)
    if plan is None:
        raise HTTPException(409, "This scenario version has no plan yet: POST /api/scenarios/{id}/plan first")
    return plan


def summary(db: Session, s: Scenario) -> dict:
    """Light: never loads version states (they are large)."""
    row = db.execute(select(ScenarioVersion.version_no).where(ScenarioVersion.id == s.current_version_id)).first()
    count = db.scalar(select(func.count()).select_from(ScenarioVersion).where(ScenarioVersion.scenario_id == s.id))
    return {"id": s.id, "name": s.name, "current_version_id": s.current_version_id,
            "current_version_no": row[0] if row else None, "version_count": count,
            "created_at": s.created_at.isoformat()}


def full(db: Session, s: Scenario) -> dict:
    cur = db.get(ScenarioVersion, s.current_version_id) if s.current_version_id else None
    plan = current_plan(db, cur.id) if cur else None
    versions = db.execute(select(ScenarioVersion.id, ScenarioVersion.version_no, ScenarioVersion.source,
                                 ScenarioVersion.created_at)
                          .where(ScenarioVersion.scenario_id == s.id).order_by(ScenarioVersion.version_no)).all()
    return {**summary(db, s),
            "versions": [{"id": i, "version_no": n, "source": src, "created_at": at.isoformat()}
                         for i, n, src, at in versions],
            "current_state": cur.state_json if cur else None,
            "current_plan_id": plan.id if plan else None,
            "current_plan": plan.plan_json if plan else None}


# ------------------------------------------------------------------ scenarios
@router.post("")
def create_scenario(req: ScenarioCreateRequest, db: Session = Depends(get_db), _=Depends(PLANNER)):
    state = service.generate_scenario(req.size, req.tightness, req.seed, req.trap_groups)
    s = Scenario(id=uuid4().hex, name=req.name, current_version_id=None)
    db.add(s)
    db.flush()                                    # parent row first (FK order is not inferred)
    v = ScenarioVersion(id=uuid4().hex, scenario_id=s.id, version_no=1, state_json=state, source="generated")
    db.add(v)
    db.flush()                                    # version row must exist before it is referenced
    s.current_version_id = v.id
    db.commit()
    return full(db, s)


@router.get("")
def list_scenarios(db: Session = Depends(get_db), _=Depends(ANY)):
    return [summary(db, s) for s in db.scalars(select(Scenario).order_by(Scenario.created_at.desc())).all()]


@router.get("/{scenario_id}")
def get_scenario(scenario_id: str, db: Session = Depends(get_db), _=Depends(ANY)):
    s = db.get(Scenario, scenario_id)
    if not s:
        raise HTTPException(404, "Scenario not found")
    return full(db, s)


@router.get("/{scenario_id}/current")
def get_current(scenario_id: str, db: Session = Depends(get_db), _=Depends(ANY)):
    """The single source of truth for the UI: current version, state AND plan, from the database."""
    s, v = load(db, scenario_id)
    plan = current_plan(db, v.id)
    return {"scenario_id": s.id, "version_id": v.id, "version_no": v.version_no, "source": v.source,
            "state": v.state_json, "plan_id": plan.id if plan else None,
            "plan": plan.plan_json if plan else None}


@router.post("/{scenario_id}/reset")
def reset_scenario(scenario_id: str, db: Session = Depends(get_db), user: User = Depends(PLANNER)):
    s = db.get(Scenario, scenario_id)
    if not s:
        raise HTTPException(404, "Scenario not found")
    first = db.scalars(select(ScenarioVersion).where(ScenarioVersion.scenario_id == s.id)
                       .order_by(ScenarioVersion.version_no).limit(1)).first()
    before = s.current_version_id
    s.current_version_id = first.id
    db.add(Decision(id=uuid4().hex, scenario_id=s.id, scenario_version_id=first.id, actor_user_id=user.id,
                    action="reset", reason=f"reset from version {before}", metrics_json={}, diff_json=[]))
    db.commit()
    return full(db, s)


# ------------------------------------------------------------------ scenario-bound engine calls
@router.post("/{scenario_id}/impact")
def impact(scenario_id: str, req: ScenarioImpactRequest, db: Session = Depends(get_db), _=Depends(ANY)):
    """Instant 'disruption detected' panel, computed from the stored state + plan."""
    _, v = load(db, scenario_id)
    plan = need_plan(db, v)
    return engine_call(service.assess_impact, v.state_json, plan.plan_json, req.events)


@router.get("/{scenario_id}/validate")
def validate(scenario_id: str, db: Session = Depends(get_db), _=Depends(ANY)):
    _, v = load(db, scenario_id)
    plan = need_plan(db, v)
    return {"violations": engine_call(service.validate_plan, v.state_json, plan.plan_json)}


@router.post("/{scenario_id}/plan")
def plan_scenario(scenario_id: str, req: ScenarioPlanRequest, db: Session = Depends(get_db),
                  jobs=Depends(get_jobs), user: User = Depends(PLANNER)):
    """Background job. On completion the plan is attached to the CURRENT version automatically."""
    s, v = load(db, scenario_id)
    job_id = jobs.submit("create_plan", {
        "state": v.state_json, "time_limit": req.time_limit, "seed": req.seed, "workers": req.workers,
        "scenario_id": s.id, "scenario_version_id": v.id, "created_by": user.username})
    return {"job_id": job_id, "status": "QUEUED", "scenario_version_id": v.id}


@router.post("/{scenario_id}/replan")
def replan_scenario(scenario_id: str, req: ScenarioReplanRequest, db: Session = Depends(get_db),
                    jobs=Depends(get_jobs), user: User = Depends(PLANNER)):
    """Background job producing plan A/B/C. It changes nothing: approve one via POST /api/decisions."""
    s, v = load(db, scenario_id)
    plan = need_plan(db, v)
    engine_call(service.assess_impact, v.state_json, plan.plan_json, req.events)   # reject bad events now
    for e in req.events:
        db.add(EventRecord(id=uuid4().hex, scenario_id=s.id, event_json=e, time=int(e["time"])))
    db.commit()
    job_id = jobs.submit("replan_options", {
        "state": v.state_json, "plan": plan.plan_json, "events": req.events, "time_limit": req.time_limit,
        "seed": req.seed, "robustness_trials": req.robustness_trials, "workers": req.workers,
        "include_state": True, "scenario_id": s.id, "scenario_version_id": v.id, "base_plan_id": plan.id,
        "created_by": user.username})
    return {"job_id": job_id, "status": "QUEUED", "scenario_version_id": v.id}
