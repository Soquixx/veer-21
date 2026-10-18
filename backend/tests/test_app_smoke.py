from fastapi.testclient import TestClient

from backend.app import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] in {"ok", "degraded"}


def test_protected_routes_need_a_token():
    with TestClient(app) as client:
        assert client.get("/api/scenarios").status_code == 401
        assert client.get("/api/jobs/does-not-exist").status_code == 401
