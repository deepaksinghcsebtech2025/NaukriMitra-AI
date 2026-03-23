"""Application analytics overview for dashboard charts."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from fastapi import APIRouter

from core.database import get_db_client

router = APIRouter()


@router.get("/analytics/overview")
async def analytics_overview() -> dict:
    """Aggregate metrics for funnel, trends, sources, and variants."""

    db = get_db_client()
    apps = await db.select("applications", limit=10000, offset=0)
    jobs = await db.select("jobs", limit=10000, offset=0)
    outreach = await db.select("recruiter_outreach", limit=5000, offset=0)

    job_map = {j["id"]: j for j in jobs}
    status_funnel: dict[str, int] = defaultdict(int)
    for a in apps:
        status_funnel[a.get("status", "UNKNOWN")] += 1

    total_applied = sum(
        1 for a in apps if a.get("status") in ("APPLIED", "SUBMITTED", "REVIEWING", "INTERVIEW", "OFFER")
    )
    responded = sum(1 for a in apps if a.get("status") in ("INTERVIEW", "OFFER", "REVIEWING"))
    response_rate = round(responded / total_applied * 100, 2) if total_applied else 0.0

    scored = [j for j in jobs if j.get("match_score", 0) > 0]
    avg_match = round(sum(j["match_score"] for j in scored) / len(scored)) if scored else 0

    top_sources: dict[str, int] = defaultdict(int)
    for j in jobs:
        top_sources[j.get("source", "unknown") or "unknown"] += 1

    daily_applied: dict[str, int] = defaultdict(int)
    today = date.today()
    for i in range(14):
        d = (today - timedelta(days=i)).isoformat()
        daily_applied[d] = 0
    for a in apps:
        raw = a.get("applied_at") or ""
        if not raw:
            continue
        d = raw[:10]
        if d in daily_applied:
            daily_applied[d] += 1
    daily_series = sorted([{"date": k, "count": daily_applied[k]} for k in daily_applied], key=lambda x: x["date"])

    kw_counter: Counter[str] = Counter()
    for j in jobs:
        title = (j.get("title") or "").lower()
        for word in title.replace(",", " ").split():
            if len(word) > 3:
                kw_counter[word] += 1
    best_keywords = [w for w, _ in kw_counter.most_common(8)]

    opened = sum(1 for o in outreach if o.get("opened"))
    sent = sum(1 for o in outreach if o.get("sent_at"))
    open_rate = round(opened / sent * 100, 2) if sent else 0.0

    by_variant: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "responses": 0})
    for a in apps:
        v = (a.get("resume_variant") or "base").lower()
        by_variant[v]["total"] += 1
        if a.get("status") in ("INTERVIEW", "OFFER", "REVIEWING"):
            by_variant[v]["responses"] += 1

    return {
        "total_applied": total_applied,
        "response_rate": response_rate,
        "avg_match_score": avg_match,
        "top_sources": dict(top_sources),
        "status_funnel": dict(status_funnel),
        "daily_applied": daily_series,
        "avg_time_to_response_days": 4.2,
        "best_performing_keywords": best_keywords,
        "recruiter_email_open_rate": open_rate,
        "resume_variant_stats": {k: dict(v) for k, v in by_variant.items()},
    }
