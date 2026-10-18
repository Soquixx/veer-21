from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from engine import service
from ..db.models import Decision, Job, PlanRecord, Scenario, ScenarioVersion, User
from ..db.session import get_db
from ..deps import engine_call
from ..schemas import DecisionRequest
from ..security import current_user, require_roles

router = APIRouter(prefix="/decisions", tags=["decisions"])


def _pick(result: dict, label: str):
    """(plan, metrics, changes-or-None) of the named option, taken from the STORED job result."""
    if label == "greedy_patch":
        base = result.get("baseline_greedy_patch")
        return (base["plan"], base["metrics"], None) if base else None
    for opt in result.get("options", []):
        if opt.get("label") == label:
            return opt["plan"], opt["metrics"], opt.get("changes", [])
    return None


@router.post("")
def decision(req: DecisionRequest, db: Session = Depends(get_db),
             user: User = Depends(require_roles("approver"))):
    """Human-in-the-loop gate. The client names a job and an option; the SERVER takes the plan and the
    post-event state from the stored job result, re-validates it, and only then writes a new version.
    Nothing the browser sends can become the operational plan."""
    # Row lock: two approvers racing on the same scenario are serialised (no-op on SQLite).
    scenario = db.execute(select(Scenario).where(Scenario.id == req.scenario_id).with_for_update()).scalar_one_or_none()
    if scenario is None:
        raise HTTPException(404, "Scenario not found")

    def audit(action: str, version_id: str | None, **kw) -> Decision:
        row = Decision(id=uuid4().hex, scenario_id=scenario.id, scenario_version_id=version_id,
                       actor_user_id=user.id, action=action, reason=req.reason,
                       metrics_json=kw.pop("metrics", None) or {}, diff_json=kw.pop("diff", None) or [], **kw)
        db.add(row)
        return row

    if req.action == "rollback":
        if not req.rollback_version_id:
            raise HTTPException(422, "rollback_version_id is required")
        version = db.get(ScenarioVersion, req.rollback_version_id)
        if version is None or version.scenario_id != scenario.id:
            raise HTTPException(404, "Rollback version not found for this scenario")
        scenario.current_version_id = version.id
        row = audit("rollback", version.id)
        db.commit()
        return {"status": "rolled_back", "decision_id": row.id, "scenario_version_id": version.id}

    # ---- approve / reject: both reference a completed replan job for the CURRENT version
    if not req.job_id or not req.option_label:
        raise HTTPException(422, "job_id and option_label are required")
    job = db.get(Job, req.job_id)
    inp = (job.input_json or {}) if job else {}
    if job is None or job.type != "replan_options" or inp.get("scenario_id") != scenario.id:
        raise HTTPException(404, "Replan job not found for this scenario (sandbox jobs cannot be approved)")
    if job.status != "COMPLETED":
        raise HTTPException(409, f"Job is {job.status}, not COMPLETED")
    if inp.get("scenario_version_id") != scenario.current_version_id:
        raise HTTPException(409, "Scenario changed since this replan was computed; run the replan again")

    result = job.result_json or {}
    picked = _pick(result, req.option_label)
    if picked is None:
        have = [o.get("label") for o in result.get("options", [])] + ["greedy_patch"]
        raise HTTPException(404, f"No option {req.option_label!r}; available: {have}")
    plan, metrics, changes = picked

    if req.action == "reject":
        row = audit("reject", scenario.current_version_id, job_id=job.id, option_label=req.option_label,
                    metrics=metrics, diff=changes)
        db.commit()
        return {"status": "rejected", "decision_id": row.id}

    state_after = result.get("state_after")
    if not state_after:
        raise HTTPException(422, "Job result has no state_after")
    violations = engine_call(service.validate_plan, state_after, plan)
    if violations:
        raise HTTPException(422, {"message": "Plan failed validation; not applied", "violations": violations})
    if changes is None:
        changes = engine_call(service.plan_diff, inp["plan"], plan, state_after.get("now", 0))

    version_no = (db.scalar(select(func.max(ScenarioVersion.version_no))
                            .where(ScenarioVersion.scenario_id == scenario.id)) or 0) + 1
    version = ScenarioVersion(id=uuid4().hex, scenario_id=scenario.id, version_no=version_no,
                              state_json=state_after, source=f"approved:{req.option_label}")
    db.add(version)
    db.flush()                                    # version must exist before rows that reference it
    plan_row = PlanRecord(id=uuid4().hex, scenario_version_id=version.id, plan_json=plan,
                          status=plan.get("status", "UNKNOWN"), solve_ms=float(plan.get("solve_ms", 0.0)))
    db.add(plan_row)
    db.flush()
    scenario.current_version_id = version.id
    row = audit("approve", version.id, plan_id=plan_row.id, job_id=job.id, option_label=req.option_label,
                metrics=metrics, diff=changes)
    db.commit()
    return {"status": "approved", "decision_id": row.id, "scenario_version_id": version.id,
            "version_no": version_no, "plan_id": plan_row.id}


@router.get("/{scenario_id}")
def decision_history(scenario_id: str, db: Session = Depends(get_db), _=Depends(current_user)):
    rows = db.execute(select(Decision, User.username).join(User, User.id == Decision.actor_user_id)
                      .where(Decision.scenario_id == scenario_id).order_by(Decision.created_at.desc())).all()
    return [{"id": d.id, "action": d.action, "option_label": d.option_label, "job_id": d.job_id,
             "metrics": d.metrics_json, "diff": d.diff_json, "reason": d.reason, "actor": name,
             "scenario_version_id": d.scenario_version_id, "plan_id": d.plan_id,
             "created_at": d.created_at.isoformat()} for d, name in rows]
