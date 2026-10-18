from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..db.models import Job
from ..db.session import SessionLocal, get_db
from ..deps import get_jobs
from ..jobs.manager import TERMINAL, JobManager
from ..schemas import JobStatusResponse, PlanRequest, ReplanRequest
from ..security import current_user, require_roles, user_from_token

router = APIRouter(tags=["jobs"])
PLANNER = require_roles("planner", "approver")


def _iso(d):
    return d.isoformat() if d else None


def _status(job: Job) -> JobStatusResponse:
    inp = job.input_json or {}
    return JobStatusResponse(
        id=job.id, type=job.type, status=job.status, result=job.result_json, error=job.error,
        result_ref=job.result_ref, scenario_id=inp.get("scenario_id"),
        scenario_version_id=inp.get("scenario_version_id"), created_at=_iso(job.created_at),
        started_at=_iso(job.started_at), finished_at=_iso(job.finished_at))


# ---- Sandbox endpoints: the caller supplies state/plan, nothing touches a scenario and the
# ---- result can never be approved. Real workflow: POST /api/scenarios/{id}/plan and /replan.
@router.post("/plan", response_model=dict)
def create_plan(req: PlanRequest, jobs: JobManager = Depends(get_jobs), user=Depends(PLANNER)):
    payload = req.model_dump(exclude={"scenario_version_id"})
    payload.update(created_by=user.username, sandbox=True)
    return {"job_id": jobs.submit("create_plan", payload), "status": "QUEUED"}


@router.post("/replan", response_model=dict)
def replan(req: ReplanRequest, jobs: JobManager = Depends(get_jobs), user=Depends(PLANNER)):
    payload = req.model_dump(exclude={"scenario_version_id"})
    payload.update(created_by=user.username, sandbox=True)
    return {"job_id": jobs.submit("replan_options", payload), "status": "QUEUED"}


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str, db: Session = Depends(get_db), _=Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _status(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, jobs: JobManager = Depends(get_jobs), _=Depends(PLANNER)):
    if not jobs.cancel(job_id):
        raise HTTPException(409, "Job is already running/finished: a running solve cannot be interrupted")
    return {"id": job_id, "status": "CANCELLED"}


@router.websocket("/ws/jobs/{job_id}")
async def job_socket(websocket: WebSocket, job_id: str, token: str = Query("")):
    """Status stream for one job. Browsers cannot set headers on WebSockets, so the JWT is passed
    as ?token=. Messages: {id, status, result_ref, error}; fetch the result with GET /api/jobs/{id}."""
    with SessionLocal() as db:
        user = user_from_token(token, db)
    if user is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    jobs: JobManager = websocket.app.state.jobs
    q = jobs.subscribe(job_id)                    # subscribe BEFORE reading the snapshot: no lost update
    try:
        job = jobs.get(job_id)
        if job is None:
            await websocket.send_json({"id": job_id, "status": "NOT_FOUND"})
            return
        await websocket.send_json({"id": job.id, "status": job.status, "result_ref": job.result_ref,
                                   "error": job.error})
        if job.status in TERMINAL:                # already finished: nothing more will ever be emitted
            return
        while True:
            message = await q.get()
            await websocket.send_json(message)
            if message.get("status") in TERMINAL:
                break
    except WebSocketDisconnect:
        pass
    finally:
        jobs.unsubscribe(job_id, q)
