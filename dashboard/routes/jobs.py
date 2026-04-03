"""Jobs, pipeline, and aggregate stats endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from agents.ats_checker import ATSCheckerAgent
from agents.tracker import TrackerAgent
from core.database import get_db_client

router = APIRouter()


@router.get("/jobs")
async def list_jobs(
    status: Optional[str] = None,
    search: Optional[str] = None,
    source: Optional[str] = None,
    remote_type: Optional[str] = None,
    min_score: int = 0,
    min_salary: Optional[int] = None,
    sort: str = "score",     # "score" | "date" | "salary"
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List jobs joined with application status — filterable and sortable."""

    db = get_db_client()
    jobs = await db.select("jobs", limit=2000, offset=0)
    apps = await db.select("applications", limit=2000, offset=0)
    app_map = {a["job_id"]: a for a in apps}

    result: list[dict] = []
    for job in jobs:
        app = app_map.get(job["id"], {})
        app_status = app.get("status", "UNKNOWN")

        if status and app_status != status:
            continue
        score = int(job.get("match_score") or 0)
        if min_score and score < min_score:
            continue
        if min_salary:
            sal = int(job.get("salary_min") or 0)
            if sal > 0 and sal < min_salary:
                continue
        if source:
            if source.lower() not in (job.get("source") or "").lower():
                continue
        if remote_type:
            if remote_type.lower() != (job.get("remote_type") or "unknown").lower():
                continue
        if search:
            q = search.lower()
            haystack = f"{job.get('title','')} {job.get('company','')} {job.get('description','')[:200]}".lower()
            if q not in haystack:
                continue

        result.append({
            **job,
            "app_status": app_status,
            "app_id": app.get("id"),
            "applied_at": app.get("applied_at"),
            "resume_path": app.get("resume_path"),
            "ats_score": app.get("ats_score"),
            "cover_letter": app.get("cover_letter"),
        })

    # Sort
    if sort == "date":
        result.sort(key=lambda j: j.get("discovered_at") or "", reverse=True)
    elif sort == "salary":
        result.sort(key=lambda j: int(j.get("salary_min") or 0), reverse=True)
    else:
        result.sort(key=lambda j: int(j.get("match_score") or 0), reverse=True)

    return {"jobs": result[offset: offset + limit], "total": len(result)}


@router.get("/jobs/search")
async def search_jobs(
    q: str = "",
    source: Optional[str] = None,
    remote_type: Optional[str] = None,
    min_score: int = 0,
    limit: int = 20,
) -> dict:
    """Full-text job search with highlighted matches."""

    db = get_db_client()
    jobs = await db.select("jobs", limit=2000, offset=0)

    matches = []
    q_lower = q.lower()
    for job in jobs:
        if source and source.lower() not in (job.get("source") or "").lower():
            continue
        if remote_type and remote_type != job.get("remote_type"):
            continue
        score = int(job.get("match_score") or 0)
        if score < min_score:
            continue
        title = job.get("title", "")
        company = job.get("company", "")
        desc = (job.get("description") or "")[:300]
        haystack = f"{title} {company} {desc}".lower()
        if q_lower and q_lower not in haystack:
            continue
        matches.append({
            "id": job["id"],
            "title": title,
            "company": company,
            "location": job.get("location", ""),
            "source": job.get("source", ""),
            "match_score": score,
            "salary_estimate": job.get("salary_estimate", ""),
            "remote_type": job.get("remote_type", "unknown"),
            "apply_url": job.get("apply_url", ""),
            "discovered_at": job.get("discovered_at", ""),
        })

    matches.sort(key=lambda j: j["match_score"], reverse=True)
    return {"results": matches[:limit], "total": len(matches), "query": q}


@router.get("/pipeline")
async def get_pipeline() -> dict:
    """Raw pipeline counters for Kanban."""

    return await TrackerAgent().get_pipeline_stats()


@router.get("/stats")
async def get_stats() -> dict:
    """High-level KPIs for dashboard cards."""

    stats = await TrackerAgent().get_pipeline_stats()
    total_applied = sum(
        v
        for k, v in stats.items()
        if k in ("APPLIED", "SUBMITTED", "REVIEWING", "INTERVIEW", "OFFER", "ACCEPTED")
        and isinstance(v, int)
    )
    interviews = int(stats.get("INTERVIEW", 0) or 0)
    success_rate = round(interviews / total_applied * 100) if total_applied > 0 else 0
    out: dict = {
        "total_discovered": stats.get("total_jobs", 0),
        "total_applied": total_applied,
        "interviews": interviews,
        "avg_match_score": stats.get("avg_match_score", 0),
        "today_applied": stats.get("today_applied", 0),
        "week_applied": stats.get("week_applied", 0),
        "success_rate": success_rate,
    }
    for key in (
        "DISCOVERED",
        "FILTERED",
        "TAILORED",
        "APPLIED",
        "SUBMITTED",
        "REVIEWING",
        "INTERVIEW",
        "OFFER",
        "REJECTED",
        "MANUAL_REVIEW",
        "FAILED",
    ):
        if key in stats and isinstance(stats[key], int):
            out[key] = stats[key]
    return out


@router.get("/db-status")
async def db_status() -> dict:
    """Check whether the Supabase connection is working."""
    db = get_db_client()
    if not db._configured:
        return {"status": "not_configured", "message": "Set SUPABASE_URL and SUPABASE_KEY in .env"}
    if db._unreachable:
        return {
            "status": "unreachable",
            "message": "Supabase project may be paused. Visit https://supabase.com/dashboard to unpause.",
        }
    return {"status": "ok"}


@router.get("/ats-check/{job_id}")
async def ats_check_job(job_id: str) -> dict:
    """Run ATS analysis for base resume vs this job; persist score on linked application."""

    db = get_db_client()
    job = await db.select_one("jobs", {"id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    apps = await db.select("applications", limit=500, offset=0)
    app = next((a for a in apps if str(a.get("job_id")) == str(job_id)), None)

    resume_path = Path("resumes/base_resume.txt")
    resume_text = (
        resume_path.read_text(encoding="utf-8") if resume_path.exists() else "Experienced software engineer."
    )
    desc = str(job.get("description", "") or "")
    agent = ATSCheckerAgent()
    result = await agent.check_resume(resume_text, desc)
    score = int(result.get("ats_score", 0))

    if app:
        await db.update("applications", app["id"], {"ats_score": score})
        kw = result.get("present_keywords", []) + result.get("missing_keywords", [])
        if isinstance(kw, list):
            await db.update("jobs", job_id, {"ats_keywords": kw[:30]})

    return {"job_id": job_id, "application_id": app.get("id") if app else None, **result}
