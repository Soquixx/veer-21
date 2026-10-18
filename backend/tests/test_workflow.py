"""End-to-end: generate -> plan (background job) -> suggest event -> impact -> replan (job)
-> approve (server-side) -> audit -> stale approval rejected -> rollback. Needs OR-Tools."""
import time
from uuid import uuid4

import pytest

pytest.importorskip("ortools")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402
from backend.db.models import User  # noqa: E402
from backend.db.session import SessionLocal  # noqa: E402
from backend.security import hash_password  # noqa: E402

USERS = (("viewer", "viewer"), ("planner", "planner"), ("approver", "approver"))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:                       # lifespan creates tables + starts the worker pool
        with SessionLocal.begin() as db:
            for name, role in USERS:
                db.add(User(id=uuid4().hex, username=name, password_hash=hash_password(f"pw-{name}"), role=role))
        yield c


def auth(client, name):
    r = client.post("/api/auth/login", json={"username": name, "password": f"pw-{name}"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def wait(client, headers, job_id, timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if job["status"] in ("COMPLETED", "FAILED", "CANCELLED", "ABANDONED"):
            return job
        time.sleep(0.5)
    raise AssertionError("job did not finish in time")


def test_full_workflow(client):
    viewer, planner, approver = (auth(client, n) for n, _ in USERS)

    # --- scenario, no plan yet
    sc = client.post("/api/scenarios", headers=planner,
                     json={"name": "t", "size": "S", "tightness": 0.9, "seed": 2, "trap_groups": 1})
    assert sc.status_code == 200, sc.text
    sid = sc.json()["id"]
    assert client.get(f"/api/scenarios/{sid}/current", headers=viewer).json()["plan"] is None
    assert client.post(f"/api/scenarios/{sid}/replan", headers=planner,
                       json={"events": [{"id": "e", "type": "AIRCRAFT_OUT", "time": 5, "target_id": "AC000"}]}
                       ).status_code == 409
    assert client.post("/api/scenarios", headers=viewer, json={}).status_code == 403

    # --- initial plan: background job, attached to the scenario by the SERVER
    job = client.post(f"/api/scenarios/{sid}/plan", headers=planner, json={"time_limit": 3, "seed": 2}).json()
    done = wait(client, planner, job["job_id"])
    assert done["status"] == "COMPLETED", done.get("error")
    cur = client.get(f"/api/scenarios/{sid}/current", headers=viewer).json()
    assert cur["plan"] and cur["plan"]["violations"] == [] and cur["version_no"] == 1
    v1 = cur["version_id"]

    # --- disruption: suggest, impact (instant), validate
    events = client.post(f"/api/scenarios/{sid}/events/suggest?kind=combined&seed=2", headers=planner).json()
    assert events
    imp = client.post(f"/api/scenarios/{sid}/impact", headers=viewer, json={"events": events})
    assert imp.status_code == 200 and imp.json()["impact"]["directly_affected"]
    assert client.post(f"/api/scenarios/{sid}/impact", headers=viewer,
                       json={"events": [{"id": "x", "type": "AIRCRAFT_OUT", "time": 1, "target_id": "NOPE"}]}
                       ).status_code == 422
    assert client.post(f"/api/scenarios/{sid}/impact", headers=viewer,
                       json={"events": [{"id": "x", "type": "BOGUS", "time": 1}]}).status_code == 422
    assert client.get(f"/api/scenarios/{sid}/validate", headers=viewer).json()["violations"] == []

    # --- replan job
    rj = client.post(f"/api/scenarios/{sid}/replan", headers=planner,
                     json={"events": events, "time_limit": 3, "seed": 2, "robustness_trials": 10}).json()
    rdone = wait(client, planner, rj["job_id"])
    assert rdone["status"] == "COMPLETED", rdone.get("error")
    options = rdone["result"]["options"]
    assert 1 <= len(options) <= 3 and rdone["result"]["stale"] is False
    label = options[0]["label"]

    # --- approval: only approvers; client can't inject a plan; unknown/sandbox jobs rejected
    body = {"scenario_id": sid, "action": "approve", "job_id": rj["job_id"], "option_label": label, "reason": "t"}
    assert client.post("/api/decisions", headers=viewer, json=body).status_code == 403
    assert client.post("/api/decisions", headers=planner, json=body).status_code == 403
    assert client.post("/api/decisions", headers=approver, json={**body, "job_id": "nope"}).status_code == 404
    assert client.post("/api/decisions", headers=approver, json={**body, "option_label": "ZZZ"}).status_code == 404
    ok = client.post("/api/decisions", headers=approver, json=body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["version_no"] == 2

    after = client.get(f"/api/scenarios/{sid}/current", headers=viewer).json()
    assert after["version_no"] == 2 and after["plan"] == options[0]["plan"] and after["state"] != cur["state"]

    # --- the same job can't be approved twice (scenario moved on)
    assert client.post("/api/decisions", headers=approver, json=body).status_code == 409

    # --- audit trail names the approver
    hist = client.get(f"/api/decisions/{sid}", headers=viewer).json()
    assert hist[0]["action"] == "approve" and hist[0]["actor"] == "approver" and hist[0]["option_label"] == label

    # --- rollback restores BOTH state and plan of version 1
    rb = client.post("/api/decisions", headers=approver,
                     json={"scenario_id": sid, "action": "rollback", "rollback_version_id": v1})
    assert rb.status_code == 200
    back = client.get(f"/api/scenarios/{sid}/current", headers=viewer).json()
    assert back["version_id"] == v1 and back["plan"] == cur["plan"] and back["state"] == cur["state"]


def test_sandbox_jobs_cannot_be_approved(client):
    planner, approver = auth(client, "planner"), auth(client, "approver")
    sid = client.post("/api/scenarios", headers=planner,
                      json={"name": "s", "size": "S", "seed": 4}).json()["id"]
    state = client.get(f"/api/scenarios/{sid}/current", headers=planner).json()["state"]
    job = client.post("/api/plan", headers=planner, json={"state": state, "time_limit": 2}).json()
    assert wait(client, planner, job["job_id"])["status"] == "COMPLETED"
    r = client.post("/api/decisions", headers=approver,
                    json={"scenario_id": sid, "action": "approve", "job_id": job["job_id"], "option_label": "x"})
    assert r.status_code == 404
