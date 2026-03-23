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
        jobs_data = [
            {
                "id": "j1",
                "title": "T",
                "company": "C",
                "location": "L",
                "match_score": 80,
                "source": "linkedin",
                "description": "Python backend",
            }
        ]
        apps_data = [
            {
                "id": "a1",
                "job_id": "j1",
                "status": "DISCOVERED",
                "ats_score": 0,
                "cover_letter": "",
                "interview_prep": {},
                "applied_at": None,
                "resume_path": None,
                "outreach_sent": False,
                "resume_variant": "base",
            }
        ]

        async def select(self, table, filters=None, limit=100, offset=0):
            filters = filters or {}
            if table == "jobs":
                rows = list(self.jobs_data)
            elif table == "applications":
                rows = list(self.apps_data)
            elif table == "recruiter_outreach":
                rows = []
            elif table == "resume_variants":
                rows = []
            else:
                rows = []
            for key, value in filters.items():
                rows = [r for r in rows if r.get(key) == value]
            return rows[offset : offset + limit]

        async def select_one(self, table, filters=None):
            rows = await self.select(table, filters, limit=1, offset=0)
            return rows[0] if rows else None

        async def insert(self, table, data):
            return {**data, "id": "new-row"}

        async def update(self, table, record_id, data):
            return {"id": record_id, **data}

    fake = FakeDB()

    def get_fake_db():
        return fake

    for mod in (
        "dashboard.routes.jobs",
        "dashboard.routes.applications",
        "dashboard.routes.analytics",
        "dashboard.routes.resume_routes",
        "dashboard.routes.track",
        "agents.base",
    ):
        monkeypatch.setattr(f"{mod}.get_db_client", get_fake_db)

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


def test_analytics_overview(client: TestClient):
    r = client.get("/api/analytics/overview")
    assert r.status_code == 200
    body = r.json()
    assert "status_funnel" in body
    assert "daily_applied" in body


def test_applications_interview_prep(client: TestClient):
    r = client.get("/api/applications/a1/interview-prep")
    assert r.status_code == 200
    assert r.json().get("application_id") == "a1"


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
