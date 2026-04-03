"""Trigger agents from the dashboard."""

from __future__ import annotations

import asyncio
import importlib

from fastapi import APIRouter

from core.logger import logger

router = APIRouter()

AGENT_MAP = {
    "scraper": "agents.scraper.ScraperAgent",
    "filter": "agents.filter.FilterAgent",
    "resume": "agents.resume.ResumeAgent",
    "apply": "agents.apply.ApplyAgent",
    "notify": "agents.notifier.NotifierAgent",
    "ats_checker": "agents.ats_checker.ATSCheckerAgent",
    "recruiter_outreach": "agents.recruiter_outreach.RecruiterOutreachAgent",
    "interview_coach": "agents.interview_coach.InterviewCoachAgent",
    "linkedin_optimizer": "agents.linkedin_optimizer.LinkedInOptimizerAgent",
    "resume_variant": "agents.resume.ResumeVariantAgent",
}


async def _run_agent(module_path: str) -> None:
    """Import agent class and await run()."""

    module_name, class_name = module_path.rsplit(".", 1)
    mod = importlib.import_module(module_name)
    cls = getattr(mod, class_name)
    await cls().run()


def _task_error_handler(task: asyncio.Task) -> None:
    """Log unhandled exceptions from background agent tasks."""

    if not task.cancelled() and task.exception():
        logger.error("Background agent task failed: {}", task.exception())


@router.post("/agents/{name}/run")
async def run_agent(name: str) -> dict:
    """Fire-and-forget agent execution."""

    if name not in AGENT_MAP:
        return {"error": f"Unknown agent: {name}"}
    task = asyncio.create_task(_run_agent(AGENT_MAP[name]))
    task.add_done_callback(_task_error_handler)
    return {"started": True, "agent": name}
