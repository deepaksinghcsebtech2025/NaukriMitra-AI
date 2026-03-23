"""Read-only config exposure and cached overrides."""

from __future__ import annotations

import json

from fastapi import APIRouter

from core.cache import get_cache_client
from core.config import get_settings

router = APIRouter()


@router.get("/config")
async def get_config() -> dict:
    """Return non-secret settings for the SPA."""

    s = get_settings()
    return {
        "applicant_name": s.applicant_name,
        "applicant_email": s.applicant_email,
        "applicant_phone": s.applicant_phone,
        "applicant_location": s.applicant_location,
        "applicant_linkedin": s.applicant_linkedin,
        "applicant_github": s.applicant_github,
        "search_keywords": s.search_keywords,
        "search_locations": s.search_locations,
        "match_threshold": s.match_threshold,
        "max_applications_per_day": s.max_applications_per_day,
        "scrape_interval_hours": s.scrape_interval_hours,
        "llm_primary": s.llm_primary,
        "exclude_companies": s.exclude_companies,
        "exclude_keywords": s.exclude_keywords,
        "min_salary_inr": s.min_salary_inr,
        "prefer_companies": s.prefer_companies,
        "max_experience_required": s.max_experience_required,
        "work_type": s.work_type,
        "company_size": s.company_size,
        "target_roles": s.target_roles,
        "resume_active_variant": s.resume_active_variant,
    }


@router.post("/config")
async def update_config(data: dict) -> dict:
    """Store overrides in Redis (runtime merge not applied to Settings singleton)."""

    cache = get_cache_client()
    await cache.set("config:overrides", json.dumps(data), ttl_seconds=86400 * 30)
    return {"updated": True, "fields": list(data.keys())}
