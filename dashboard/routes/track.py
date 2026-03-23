"""Email open tracking pixel."""

from __future__ import annotations

import base64

from fastapi import APIRouter, Response

from core.database import get_db_client

router = APIRouter()

_GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


@router.get("/track/open/{outreach_id}")
async def track_open(outreach_id: str) -> Response:
    """Record open on recruiter_outreach and return 1x1 GIF."""

    db = get_db_client()
    try:
        await db.update("recruiter_outreach", outreach_id, {"opened": True})
    except Exception:
        pass
    return Response(content=_GIF, media_type="image/gif")
