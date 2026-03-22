"""Filter agent scoring structure."""

import asyncio
from unittest.mock import AsyncMock, patch

from agents.filter import FilterAgent


def test_score_job_shape():
    async def _run() -> None:
        agent = FilterAgent()
        fake = {
            "match_score": 82,
            "reasons": ["a", "b", "c"],
            "skills_gap": ["x"],
            "tailoring_hints": ["h1", "h2", "h3"],
            "apply_recommended": True,
        }
        job = {
            "id": "00000000-0000-0000-0000-000000000001",
            "title": "Python Engineer",
            "company": "Acme",
            "location": "Remote",
            "description": "Build APIs",
        }

        with patch.object(agent.llm, "extract_json", new_callable=AsyncMock) as ej:
            ej.return_value = fake
            with patch.object(agent.db, "update", new_callable=AsyncMock) as up:
                up.return_value = {}
                result = await agent.score_job(job)

        assert result["match_score"] == 82
        assert isinstance(result["reasons"], list)
        assert isinstance(result["skills_gap"], list)
        assert isinstance(result["tailoring_hints"], list)
        assert result["apply_recommended"] is True
        assert 0 <= int(result["match_score"]) <= 100

    asyncio.run(_run())
