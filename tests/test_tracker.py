"""Tracker transitions and stats."""

import asyncio

import pytest

from agents.tracker import TrackerAgent
from core.exceptions import AgentError


class FakeDB:
    def __init__(self) -> None:
        self.apps = {
            "a1": {"id": "a1", "status": "DISCOVERED", "job_id": "j1", "applied_at": None},
        }
        self.logs: list = []

    async def select_one(self, table, filters):
        if table == "applications":
            return self.apps.get(filters.get("id"))
        return None

    async def update(self, table, record_id, data):
        if table == "applications":
            self.apps[record_id].update(data)
            return self.apps[record_id]
        return {}

    async def insert(self, table, data):
        self.logs.append((table, data))
        return {"id": "log-1"}

    async def select(self, table, filters=None, limit=100, offset=0):
        if table == "applications":
            return list(self.apps.values())
        if table == "jobs":
            return [{"id": "j1", "match_score": 80}]
        return []


def test_valid_transition():
    async def _run() -> None:
        agent = TrackerAgent()
        agent.db = FakeDB()
        out = await agent.transition("a1", "FILTERED", reason="test")
        assert out["status"] == "FILTERED"

    asyncio.run(_run())


def test_invalid_transition_raises():
    async def _run() -> None:
        agent = TrackerAgent()
        agent.db = FakeDB()
        await agent.transition("a1", "FILTERED")
        with pytest.raises(AgentError):
            await agent.transition("a1", "INTERVIEW")

    asyncio.run(_run())


def test_pipeline_stats_keys():
    async def _run() -> None:
        agent = TrackerAgent()
        agent.db = FakeDB()
        stats = await agent.get_pipeline_stats()
        assert "today_applied" in stats
        assert "week_applied" in stats
        assert "avg_match_score" in stats
        assert "total_jobs" in stats

    asyncio.run(_run())
