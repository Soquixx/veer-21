from __future__ import annotations

import asyncio
import multiprocessing
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..db.models import Job, PlanRecord, Scenario
from ..db.session import SessionLocal
from ..settings import settings

ACTIVE = ("QUEUED", "RUNNING")
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "ABANDONED"}


def _run_engine_job(job_id: str, kind: str, payload: dict) -> dict:
    # Top-level on purpose: the pool uses the "spawn" start method, so this module is re-imported
    # in the worker. The worker marks the job RUNNING (a ProcessPool Future has no "started" hook;
    # with max_workers=1 later jobs genuinely wait in QUEUED).
    from datetime import datetime, timezone
    from ..db.models import Job as JobModel
    from ..db.session import SessionLocal
    with SessionLocal.begin() as db:
        job = db.get(JobModel, job_id)
        if job and job.status == "QUEUED":
            job.status = "RUNNING"
            job.started_at = datetime.now(timezone.utc)
    from engine import service

    if kind == "create_plan":
        return service.create_plan(
            payload["state"], time_limit=payload.get("time_limit", 10.0),
            seed=payload.get("seed", 0), workers=payload.get("workers"))
    if kind == "replan_options":
        return service.replan_options(
            payload["state"], payload["plan"], payload["events"],
            time_limit=payload.get("time_limit", 5.0), seed=payload.get("seed", 0),
            robustness_trials=payload.get("robustness_trials", 60),
            include_state=payload.get("include_state", True), workers=payload.get("workers"))
    raise ValueError(f"Unsupported job type: {kind}")


def timeout_for(kind: str, payload: dict) -> float:
    """create_plan = greedy + one solve; replan_options = up to 5 sweep solves + patch + stress."""
    tl = float(payload.get("time_limit", 10.0))
    factor = 2.0 if kind == "create_plan" else 7.0
    return min(float(settings.job_max_seconds), tl * factor + settings.job_overhead_seconds)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobManager:
    def __init__(self) -> None:
        self.executor: ProcessPoolExecutor | None = None
        self.futures: dict[str, Future] = {}
        self.broadcast: dict[str, set[asyncio.Queue]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ lifecycle
    @staticmethod
    def _new_pool() -> ProcessPoolExecutor:
        # "spawn" everywhere: forking a process that holds open Postgres connections (Linux default)
        # lets parent and child share sockets and corrupt each other's sessions.
        return ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.executor = self._new_pool()

    async def shutdown(self) -> None:
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.executor = None

    def _recycle_pool(self, kill: bool = False) -> None:
        """Replace a broken / hung pool. kill=True also terminates the stuck worker process."""
        old, self.executor = self.executor, self._new_pool()
        if old is not None:
            if kill:
                for proc in list(getattr(old, "_processes", {}).values()):
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            old.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ db helpers
    def _finish(self, job_id: str, **changes: Any) -> bool:
        """Apply a terminal update only if the job is still active (first writer wins)."""
        with SessionLocal.begin() as db:
            job = db.get(Job, job_id)
            if job is None or job.status not in ACTIVE:
                return False
            for k, v in changes.items():
                setattr(job, k, v)
            return True

    def get(self, job_id: str) -> Job | None:
        with SessionLocal() as db:
            return db.get(Job, job_id)

    # ------------------------------------------------------------------ pub/sub
    async def _emit(self, job_id: str, payload: dict) -> None:
        for q in list(self.broadcast.get(job_id, set())):
            await q.put(payload)

    def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.broadcast.setdefault(job_id, set()).add(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        if job_id in self.broadcast:
            self.broadcast[job_id].discard(q)
            if not self.broadcast[job_id]:
                self.broadcast.pop(job_id, None)

    async def _emit_current(self, job_id: str) -> None:
        job = self.get(job_id)
        if job:
            await self._emit(job_id, {"id": job.id, "status": job.status,
                                      "result_ref": job.result_ref, "error": job.error})

    # ------------------------------------------------------------------ submit
    def _dispatch(self, job_id: str, kind: str, payload: dict) -> Future:
        for attempt in (1, 2):
            try:
                if self.executor is None:
                    raise RuntimeError("Job manager is not running")
                return self.executor.submit(_run_engine_job, job_id, kind, payload)
            except (BrokenProcessPool, RuntimeError):
                if attempt == 2 or self.executor is None:
                    raise
                self._recycle_pool()                      # worker died earlier: start a fresh one
        raise RuntimeError("unreachable")

    def submit(self, kind: str, payload: dict) -> str:
        if not self.executor or not self.loop:
            raise RuntimeError("Job manager is not running")
        job_id = uuid4().hex
        with SessionLocal.begin() as db:
            db.add(Job(id=job_id, type=kind, status="QUEUED", input_json=payload, created_at=_now()))
        try:
            future = self._dispatch(job_id, kind, payload)
        except Exception as exc:
            self._finish(job_id, status="FAILED", error=f"could not start worker: {exc}", finished_at=_now())
            raise
        self.futures[job_id] = future
        future.add_done_callback(
            lambda f, jid=job_id: asyncio.run_coroutine_threadsafe(self._complete(jid, f), self.loop))
        asyncio.run_coroutine_threadsafe(self._watch(job_id, future, timeout_for(kind, payload)), self.loop)
        asyncio.run_coroutine_threadsafe(self._emit(job_id, {"id": job_id, "status": "QUEUED"}), self.loop)
        return job_id

    # ------------------------------------------------------------------ completion
    async def _watch(self, job_id: str, future: Future, timeout: float) -> None:
        """Fail a job that overruns its budget and replace the stuck worker."""
        try:
            await asyncio.wait_for(asyncio.wrap_future(future), timeout)
        except asyncio.TimeoutError:
            if not future.done() and self._finish(job_id, status="FAILED", finished_at=_now(),
                                                  error=f"timed out after {timeout:.0f}s"):
                self.futures.pop(job_id, None)
                self._recycle_pool(kill=True)
                await self._emit_current(job_id)
        except BaseException:
            pass                                          # outcome is handled by _complete

    async def _complete(self, job_id: str, future: Future) -> None:
        try:
            if future.cancelled():
                self._finish(job_id, status="CANCELLED", finished_at=_now(),
                             error="cancelled before it started (user request or worker restart)")
            else:
                try:
                    result = future.result()
                except Exception as exc:                  # engine error, BrokenProcessPool, ...
                    # A broken pool is replaced lazily by _dispatch() on the next submit.
                    self._finish(job_id, status="FAILED", finished_at=_now(),
                                 error=f"{type(exc).__name__}: {exc}")
                else:
                    self._store_result(job_id, result)
            await self._emit_current(job_id)
        finally:
            self.futures.pop(job_id, None)

    def _store_result(self, job_id: str, result: Any) -> None:
        job = self.get(job_id)
        if job is None or job.status not in ACTIVE:
            return                                        # timed out / cancelled meanwhile
        payload = job.input_json or {}
        sid, vid = payload.get("scenario_id"), payload.get("scenario_version_id")
        stale = False
        if sid and vid:
            with SessionLocal() as db:
                scenario = db.get(Scenario, sid)
                stale = scenario is None or scenario.current_version_id != vid
        if isinstance(result, dict):
            result = {**result, "stale": stale}
        result_ref = None
        if job.type == "create_plan" and vid and isinstance(result, dict) and isinstance(result.get("plan"), dict):
            result_ref = uuid4().hex                      # the initial plan, attached to its version
            p = result["plan"]
            with SessionLocal.begin() as db:
                db.add(PlanRecord(id=result_ref, scenario_version_id=vid, plan_json=p,
                                  status=p.get("status", "UNKNOWN"), solve_ms=float(p.get("solve_ms", 0.0))))
        self._finish(job_id, status="COMPLETED", result_json=result, result_ref=result_ref,
                     finished_at=_now())

    # ------------------------------------------------------------------ cancel
    def cancel(self, job_id: str) -> bool:
        """Only a job that has not started can be cancelled; a running solve cannot be interrupted."""
        f = self.futures.get(job_id)
        if not f or not f.cancel():
            return False
        self._finish(job_id, status="CANCELLED", finished_at=_now(), error="cancelled by user")
        return True
