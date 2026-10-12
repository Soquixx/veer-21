from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..settings import settings

router = APIRouter(tags=["fixtures"])


def _read(name: str):
    if not settings.serve_fixtures:
        raise HTTPException(status_code=404, detail="Fixture endpoints are disabled")
    path = Path(settings.sample_data_dir) / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Fixture not found: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/state")
def state():
    return _read("scenario.json")


@router.get("/plan")
def plan():
    return _read("plan.json")


@router.get("/events")
def events():
    return _read("events.json")


@router.get("/impact")
def impact():
    return _read("impact.json")


@router.get("/replan-options")
def replan_options():
    return _read("replan_options.json")
