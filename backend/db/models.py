from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONStore = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    current_version_id: Mapped[str | None] = mapped_column(ForeignKey("scenario_versions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions: Mapped[list["ScenarioVersion"]] = relationship(
        "ScenarioVersion", back_populates="scenario", foreign_keys="ScenarioVersion.scenario_id",
        cascade="all, delete-orphan"
    )


class ScenarioVersion(Base):
    __tablename__ = "scenario_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    state_json: Mapped[dict] = mapped_column(JSONStore)
    source: Mapped[str] = mapped_column(String(64), default="generated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scenario: Mapped[Scenario] = relationship("Scenario", back_populates="versions", foreign_keys=[scenario_id])


class PlanRecord(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_version_id: Mapped[str | None] = mapped_column(ForeignKey("scenario_versions.id"), index=True)
    plan_json: Mapped[dict] = mapped_column(JSONStore)
    status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    solve_ms: Mapped[float] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"), index=True)
    event_json: Mapped[dict] = mapped_column(JSONStore)
    time: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(48), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    input_json: Mapped[dict] = mapped_column(JSONStore)
    result_json: Mapped[dict | None] = mapped_column(JSONStore, nullable=True)
    result_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id"), index=True)
    scenario_version_id: Mapped[str | None] = mapped_column(ForeignKey("scenario_versions.id"), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(32))
    option_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metrics_json: Mapped[dict] = mapped_column(JSONStore, default=dict)
    diff_json: Mapped[list] = mapped_column(JSONStore, default=list)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
