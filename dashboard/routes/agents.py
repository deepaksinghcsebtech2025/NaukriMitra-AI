"""Trigger agents from the dashboard."""

from __future__ import annotations

import asyncio
import importlib

from fastapi import APIRouter

router = APIRouter()

AGENT_MAP = {
    "scraper": "agents.scraper.ScraperAgent",
    "filter": "agents.filter.FilterAgent",
    "resume": "agents.resume.ResumeAgent",
    "apply": "agents.apply.ApplyAgent",
    "notify": "agents.notifier.NotifierAgent",
}


async def _run_agent(module_path: str) -> None:
    """Import agent class and await run()."""

    module_name, class_name = module_path.rsplit(".", 1)
    mod = importlib.import_module(module_name)
    cls = getattr(mod, class_name)
    await cls().run()


@router.post("/agents/{name}/run")
async def run_agent(name: str) -> dict:
    """Fire-and-forget agent execution."""

    if name not in AGENT_MAP:
        return {"error": f"Unknown agent: {name}"}
    asyncio.create_task(_run_agent(AGENT_MAP[name]))
    return {"started": True, "agent": name}
