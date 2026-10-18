from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ..settings import settings
from .models import Base, Job


def make_engine(url: str):
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url.rstrip("/").endswith("sqlite"):
            kwargs["poolclass"] = StaticPool          # in-memory DBs vanish per connection
    return create_engine(url, **kwargs)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def abandon_stale_jobs() -> None:
    """Jobs cannot survive an API restart (the process pool is in-memory). Run ONLY at API startup:
    running it from a CLI would kill jobs that a live API is still solving."""
    with SessionLocal.begin() as db:
        db.query(Job).filter(Job.status.in_(["QUEUED", "RUNNING"])).update(
            {Job.status: "ABANDONED", Job.error: "Application restarted before job completion."},
            synchronize_session=False,
        )


def init_db() -> None:
    create_tables()
    abandon_stale_jobs()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
