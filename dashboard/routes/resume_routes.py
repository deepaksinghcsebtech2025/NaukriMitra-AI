"""Resume variant generation and performance API."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from agents.resume import ResumeVariantAgent
from core.database import get_db_client

router = APIRouter()


class VariantGenerateBody(BaseModel):
    """Optional single style to generate."""

    style: str | None = None


@router.get("/resume/variants")
async def list_variants() -> dict:
    """List saved variant files and DB rows."""

    db = get_db_client()
    rows = await db.select("resume_variants", limit=100, offset=0)
    files = []
    vdir = Path("resumes/variants")
    if vdir.exists():
        files = [p.name for p in vdir.glob("*.txt")]
    return {"database": rows, "files": files}


@router.post("/resume/variants")
async def create_resume_variants(body: VariantGenerateBody | None = None) -> dict:
    """Generate one variant style or all four."""

    agent = ResumeVariantAgent()
    if body and body.style:
        base = Path("resumes/base_resume.txt")
        text = base.read_text(encoding="utf-8") if base.exists() else ""
        path = await agent.create_variant(text, body.style)
        return {"generated": path}
    return await agent.run()


@router.get("/resume/performance")
async def resume_performance() -> dict:
    """A/B style stats by resume_variant on applications."""

    agent = ResumeVariantAgent()
    return await agent.analyze_performance()
