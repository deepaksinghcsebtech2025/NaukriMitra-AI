"""LinkedIn profile optimization API."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from agents.linkedin_optimizer import LinkedInOptimizerAgent
from core.config import get_settings

router = APIRouter()


class LinkedInOptimizeBody(BaseModel):
    """Optional resume override and target roles."""

    resume_text: str | None = None
    target_roles: list[str] | None = None


@router.post("/linkedin-optimize")
async def linkedin_optimize(body: LinkedInOptimizeBody | None = None) -> dict:
    """Analyze resume against target roles; returns headline, summary, skills, etc."""

    settings = get_settings()
    text = (body.resume_text if body and body.resume_text else "").strip()
    if not text:
        p = Path("resumes/base_resume.txt")
        text = p.read_text(encoding="utf-8") if p.exists() else "Software engineer."
    roles = (body.target_roles if body and body.target_roles else None) or settings.target_roles_list()
    agent = LinkedInOptimizerAgent()
    result = await agent.analyze_profile(text, roles)
    return result
