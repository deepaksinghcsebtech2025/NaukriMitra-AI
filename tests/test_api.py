"""HTTP API smoke tests."""

import pytest
from fastapi.testclient import TestClient

from agents.tracker import TrackerAgent
from dashboard.app import create_app


@pytest.fixture
def client(monkeypatch):
    """App client with DB-heavy paths stubbed."""

    async def fake_pipeline(self):
        return {
            "DISCOVERED": 1,
            "FILTERED": 0,
            "total_jobs": 1,
            "today_applied": 0,
            "week_applied": 0,
            "avg_match_score": 80,
            "INTERVIEW": 0,
            "OFFER": 0,
            "MANUAL_REVIEW": 0,
        }

    monkeypatch.setattr(TrackerAgent, "get_pipeline_stats", fake_pipeline)

    class FakeDB:
        async def select(self, table, filters=None, limit=100, offset=0):
            if table == "jobs":
                return [
                    {
                        "id": "j1",
                        "title": "T",
                        "company": "C",
                        "location": "L",
                        "match_score": 80,
                        "source": "linkedin",
                        "app_status": "DISCOVERED",
                    }
                ]
            if table == "applications":
                return [{"id": "a1", "job_id": "j1", "status": "DISCOVERED"}]
            return []

    fake = FakeDB()

    monkeypatch.setattr("dashboard.routes.jobs.get_db_client", lambda: fake)
    monkeypatch.setattr("dashboard.routes.applications.get_db_client", lambda: fake)

    with TestClient(create_app()) as c:
        yield c


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_stats(client: TestClient):
    r = client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert "total_discovered" in body
    assert "avg_match_score" in body


def test_jobs(client: TestClient):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert "jobs" in r.json()


def test_run_agent(client: TestClient, monkeypatch):
    async def noop_run_agent(_module_path: str) -> None:
        return None

    monkeypatch.setattr("dashboard.routes.agents._run_agent", noop_run_agent)
    r = client.post("/api/agents/scraper/run")
    assert r.status_code == 200
    assert r.json().get("started") is True


def test_favicon(client: TestClient):
    r = client.get("/favicon.ico")
    assert r.status_code == 204
