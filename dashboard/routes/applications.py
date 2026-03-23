"""Application CRUD helpers for manual review."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.interview_coach import InterviewCoachAgent
from agents.recruiter_outreach import RecruiterOutreachAgent
from core.config import get_settings
from core.database import get_db_client

router = APIRouter()


class StatusUpdate(BaseModel):
    """PATCH body for status updates."""

    status: str
    notes: str = ""


@router.get("/applications")
async def list_applications(
    status: Optional[str] = None,
    search: Optional[str] = None,
    source: Optional[str] = None,
    min_score: int = 0,
    max_score: int = 100,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Applications with embedded job rows."""

    db = get_db_client()
    apps = await db.select("applications", limit=500, offset=0)
    jobs = await db.select("jobs", limit=500, offset=0)
    job_map = {j["id"]: j for j in jobs}
    result: list[dict] = []
    for app in apps:
        job = job_map.get(app.get("job_id", ""), {})
        if status and app.get("status") != status:
            continue
        if search:
            q = search.lower()
            if q not in job.get("title", "").lower() and q not in job.get("company", "").lower():
                continue
        if source:
            src = (job.get("source") or "").lower()
            if source.lower() not in src:
                continue
        sc = int(job.get("match_score") or 0)
        if sc < min_score or sc > max_score:
            continue
        applied = (app.get("applied_at") or "")[:10]
        if date_from and applied and applied < date_from:
            continue
        if date_to and applied and applied > date_to:
            continue
        result.append({**app, "job": job})
    return {"applications": result[offset : offset + limit], "total": len(result)}


@router.patch("/applications/{app_id}")
async def update_application(app_id: str, body: StatusUpdate) -> dict:
    """Manually move an application (e.g. after off-site apply)."""

    db = get_db_client()
    updated = await db.update(
        "applications",
        app_id,
        {"status": body.status, "notes": body.notes},
    )
    return updated


@router.get("/applications/{app_id}/interview-prep")
async def get_interview_prep(app_id: str) -> dict:
    """Return stored interview prep kit or empty object."""

    db = get_db_client()
    apps = await db.select("applications", limit=5000, offset=0)
    app = next((a for a in apps if str(a.get("id")) == str(app_id)), None)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    prep = app.get("interview_prep") or {}
    if isinstance(prep, str):
        try:
            prep = json.loads(prep) if prep.strip() else {}
        except json.JSONDecodeError:
            prep = {}
    return {"application_id": app_id, "interview_prep": prep}


@router.post("/applications/{app_id}/interview-prep/generate")
async def generate_interview_prep(app_id: str) -> dict:
    """Build and persist interview questions + STAR answers."""

    agent = InterviewCoachAgent()
    kit = await agent.create_prep_kit(app_id)
    return kit


@router.get("/applications/{app_id}/cover-letter")
async def get_cover_letter(app_id: str) -> dict:
    """Return tailored cover letter text if present."""

    db = get_db_client()
    apps = await db.select("applications", limit=5000, offset=0)
    app = next((a for a in apps if str(a.get("id")) == str(app_id)), None)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"application_id": app_id, "cover_letter": app.get("cover_letter") or ""}


@router.post("/applications/{app_id}/recruiter-outreach")
async def post_recruiter_outreach(app_id: str) -> dict:
    """Find recruiter email, generate message, send once for this application."""

    db = get_db_client()
    apps = await db.select("applications", limit=5000, offset=0)
    app = next((a for a in apps if str(a.get("id")) == str(app_id)), None)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if app.get("outreach_sent"):
        return {"sent": False, "reason": "already_sent", "recruiter_email": app.get("recruiter_email")}

    job = await db.select_one("jobs", {"id": app["job_id"]})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    settings = get_settings()
    profile = (
        f"Name: {settings.applicant_name}\nEmail: {settings.applicant_email}\n"
        f"Phone: {settings.applicant_phone}\nYears experience: {settings.years_experience}\n"
        f"Location: {settings.applicant_location}\n"
        f"LinkedIn: {settings.applicant_linkedin}\nGitHub: {settings.applicant_github}"
    )

    agent = RecruiterOutreachAgent()
    to_email = await agent.find_recruiter_email(job.get("company", ""), job.get("title", ""))
    if not to_email:
        return {"sent": False, "reason": "no_email_found"}

    gen = await agent.generate_email(job, profile)
    subject = str(gen.get("subject", f"Regarding {job.get('title')}"))
    body_html = str(gen.get("body", "")).replace("\n", "<br/>")
    if not body_html.strip():
        return {"sent": False, "reason": "empty_body"}

    row = await db.insert(
        "recruiter_outreach",
        {
            "application_id": app["id"],
            "to_email": to_email,
            "subject": subject,
            "body": body_html,
        },
    )
    rid = str(row.get("id", uuid.uuid4()))

    ok = await agent.send_outreach(to_email, subject, body_html, rid)
    if ok:
        await db.update(
            "applications",
            app["id"],
            {
                "recruiter_email": to_email,
                "outreach_sent": True,
                "outreach_sent_at": datetime.utcnow().isoformat(),
                "outreach_subject": subject,
            },
        )
        await db.update("recruiter_outreach", rid, {"sent_at": datetime.utcnow().isoformat()})
    return {"sent": ok, "recruiter_email": to_email, "outreach_id": rid}
