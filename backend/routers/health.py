from fastapi import APIRouter
from sqlalchemy import text
from ..db.session import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    db_ok = False
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}
