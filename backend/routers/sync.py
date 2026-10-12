from __future__ import annotations

from fastapi import APIRouter, Depends

from engine import service
from ..deps import engine_call
from ..schemas import ImpactRequest, ValidateRequest, StressTestRequest
from ..security import require_roles

# Sandbox: the caller supplies state and plan. Prefer the scenario-bound /scenarios/{id}/... endpoints.
router = APIRouter(tags=["decision-support (sandbox)"])


@router.post("/impact")
def impact(req: ImpactRequest, _=Depends(require_roles("viewer", "planner", "approver"))):
    return engine_call(service.assess_impact, req.state, req.plan, req.events)


@router.post("/validate")
def validate(req: ValidateRequest, _=Depends(require_roles("viewer", "planner", "approver"))):
    return engine_call(service.validate_plan, req.state, req.plan)


@router.post("/stress-test")
def stress(req: StressTestRequest, _=Depends(require_roles("planner", "approver"))):
    return engine_call(service.stress, req.state, req.plan, trials=req.trials, seed=req.seed)
