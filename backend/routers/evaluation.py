from __future__ import annotations

import csv
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from ..security import require_roles
from ..settings import settings

router = APIRouter(tags=["evaluation"])


@router.get("/evaluation")
def evaluation(
    file: str = Query("benchmark_results.csv", pattern=r"^[A-Za-z0-9_.-]+\.csv$"),
    _=Depends(require_roles("viewer", "planner", "approver")),
):
    # Only read CSV files from the configured benchmark directory; no arbitrary path traversal.
    root = Path(settings.benchmark_dir).resolve()
    path = (root / file).resolve()
    if root not in path.parents and path != root:
        raise HTTPException(400, "Invalid evaluation file")
    if not path.exists():
        raise HTTPException(404, f"Evaluation file not found: {file}")
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {"source": file, "rows": rows, "count": len(rows)}
