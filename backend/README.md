# AirOps backend

FastAPI + Postgres around the decision engine. Rules: import the engine **only** through
`engine.service`; never edit `engine/`; the server, not the browser, owns state and plans.

## Run with Docker (recommended)
```
copy .env.example .env            # Windows (cp on macOS/Linux); then edit the secrets
docker compose up --build -d
docker compose run --rm api python -m backend.seed --username planner  --password "<pw>" --role planner
docker compose run --rm api python -m backend.seed --username approver --password "<pw>" --role approver
docker compose run --rm api python -m backend.seed --username viewer   --password "<pw>" --role viewer
```
Open http://localhost:8000/docs and http://localhost:8000/health.
Logs: `docker compose logs -f api` | stop: `docker compose down` | wipe DB: `docker compose down -v`.
**After pulling a version that changes tables you must run `docker compose down -v` once** (tables are
created with `create_all`, there are no migrations).

## Run without Docker
```
pip install -r requirements.txt -r backend/requirements.txt
set AIROPS_DATABASE_URL=sqlite+pysqlite:///./airops.db            (PowerShell: $env:AIROPS_DATABASE_URL=...)
python -m backend.seed --username planner --password "<pw>" --role planner
uvicorn backend.app:app --port 8000          # do NOT use --reload: it kills the solver process
```

## Tests
`pytest backend/tests` (needs OR-Tools for the end-to-end test; it uses a temp SQLite file).

## The workflow (all endpoints under /api, JWT bearer; viewer < planner < approver)
| Step | Endpoint | Role | Sync? |
|---|---|---|---|
| login | `POST /auth/login` | - | sync |
| create scenario | `POST /scenarios` | planner | sync |
| current state + plan | `GET /scenarios/{id}/current` | viewer | sync |
| initial plan | `POST /scenarios/{id}/plan` -> `{job_id}` | planner | **job** |
| suggest disruption | `POST /scenarios/{id}/events/suggest?kind=combined` | planner | sync |
| what broke | `POST /scenarios/{id}/impact` `{events}` | viewer | sync (instant) |
| plan A/B/C | `POST /scenarios/{id}/replan` `{events}` -> `{job_id}` | planner | **job** |
| job status | `GET /jobs/{id}` or `WS /ws/jobs/{id}?token=<jwt>` | viewer | - |
| approve / reject / rollback | `POST /decisions` | approver | sync |
| audit trail | `GET /decisions/{scenario_id}` | viewer | sync |
| fused data picture | `GET /provenance` | viewer | sync |
| events from fresh fused data | `POST /fusion/events` | planner | sync |
| benchmark tables | `GET /evaluation`, `GET /evaluation/{name}` | - | sync |
| dev fixtures | `GET /fixtures/{scenario,plan,events,impact,replan_options}` | - | sync |

`POST /decisions` body: `{scenario_id, action: approve|reject|rollback, job_id, option_label, reason}`
(rollback: `rollback_version_id`). `option_label` is one of the job's option labels or `greedy_patch`.
The server reads the plan from the stored job result, re-validates it, and writes a new version.

`POST /api/plan` and `POST /api/replan` (client supplies state/plan) are **sandbox** calls: their
results can never be approved.

## Things the UI must know
- Time is in 15-minute slots from scenario start.
- `options` has 1-3 plans; render what comes back. `plan.status` containing `HINT` = fast heuristic result (still valid).
- Job statuses: QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED, ABANDONED (API restarted mid-job).
  A result's `stale: true` means the scenario changed since it was computed; approval will return 409.
- Run ONE API process (the single solver worker and job bookkeeping live inside it).
- All data is synthetic and the fusion feeds are simulated; the UI must say so.
