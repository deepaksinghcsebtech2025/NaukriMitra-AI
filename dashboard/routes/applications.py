"""Application CRUD helpers for manual review."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

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
