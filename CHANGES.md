# What changed vs Member 2's first version, and why

Everything keeps Member 2's structure (routers/, jobs/manager.py, fusion/, db/, Docker). Nothing in `engine/` changed.

## Correctness / security fixes
1. **Approval can no longer be forged.** `POST /api/decisions` takes `scenario_id + job_id + option_label`.
   The server reads the plan and `state_after` from the stored job result, rejects stale versions (409),
   re-runs `validate_plan` (422 on any violation), then writes a new version. The browser cannot submit a plan.
2. **The server owns state.** New scenario-bound endpoints read state/plan from the database:
   `GET /scenarios/{id}/current`, `POST /scenarios/{id}/plan|replan|impact`, `GET /scenarios/{id}/validate`.
   A finished `create_plan` job is attached to its scenario version automatically. The old
   `POST /api/plan|replan|impact|validate|stress-test` remain as **sandbox** calls whose results cannot be approved.
3. **Likely Postgres foreign-key bug fixed.** `scenarios.current_version_id` and `scenario_versions.scenario_id`
   reference each other; inserting both in one flush can hit an FK violation on Postgres (SQLite hides it because
   it does not enforce FKs by default). All writes now flush parent rows first.
4. **WebSocket requires a JWT** (`?token=`), and it no longer hangs when a job is already finished at connect time.
5. **Process pool uses `spawn`.** Forking a process that holds open Postgres connections can corrupt them.
6. **Worker recovery + timeouts.** A dead worker (`BrokenProcessPool`) is replaced on the next submit; a job that
   exceeds `min(job_max_seconds, time_limit*k + overhead)` is failed and the stuck worker is terminated.
7. **Seeding no longer kills running jobs** (`seed` used `init_db()`, which marks active jobs ABANDONED).
8. **Fusion fixed.** Readings are grouped by `(kind, key)` (a threat can no longer overwrite weather in the same
   sector); per-reading max age, STALE status, conflict flag, and `to_events()` which turns only FRESH incident
   readings into engine events. Feeds are labelled `simulated`.
9. Validation + 422s: events are validated (id/type/time), engine `KeyError/ValueError` -> 422 not 500.
   `events/suggest` no longer falls back to a fixture plan. List endpoints no longer load full states.
10. Audit: decisions store `job_id`, show the actor's username, and "reset" is audited. Approvals always create a
    NEW plan row (history is never overwritten).

## Docker
Fixtures and benchmark CSVs are mounted (no rebuild to refresh), Postgres bound to localhost, secrets via `.env`,
non-root image, API healthcheck, `settings.assert_safe()` refuses placeholder secrets outside development.

## Schema change
`decisions.job_id` was added. Run `docker compose down -v` once (no migrations).

## Honest verification status
Verified here: every file compiles; all intra-package imports resolve; a static undefined-name check is clean;
`backend/tests/test_fusion.py` passes against the real engine.
NOT run here (FastAPI/SQLAlchemy/Postgres/Docker were unavailable): the API itself, `test_workflow.py`, `test_security.py`,
the container build. Run `pytest backend/tests` and `docker compose up --build` first and report any failure.
