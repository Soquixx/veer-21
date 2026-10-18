from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db.session import init_db
from .jobs.manager import JobManager
from .settings import settings
from .routers import auth, decisions, events, evaluation, fixtures, fusion, health, jobs, scenarios, sync


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.assert_safe()
    init_db()
    manager = JobManager()
    await manager.start()
    app.state.jobs = manager
    yield
    await manager.shutdown()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

origins = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(fixtures.router, prefix=settings.api_prefix)
app.include_router(scenarios.router, prefix=settings.api_prefix)
app.include_router(events.router, prefix=settings.api_prefix)
app.include_router(fusion.router, prefix=settings.api_prefix)
app.include_router(jobs.router, prefix=settings.api_prefix)
app.include_router(sync.router, prefix=settings.api_prefix)
app.include_router(decisions.router, prefix=settings.api_prefix)
app.include_router(evaluation.router, prefix=settings.api_prefix)
