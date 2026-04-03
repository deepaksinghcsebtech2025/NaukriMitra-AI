"""Startup validation: check environment variables and service connectivity."""

from __future__ import annotations

from core.config import get_settings
from core.logger import logger


def validate_environment() -> dict[str, dict]:
    """Check all required and optional env vars; return status report.

    Returns dict like:
        {
            "supabase": {"status": "ok" | "missing" | "warning", "detail": "..."},
            "redis": {...},
            "llm": {...},
            ...
        }
    """
    s = get_settings()
    report: dict[str, dict] = {}

    # Supabase (required for core functionality)
    if s.supabase_url and s.supabase_key:
        if s.supabase_key.startswith("sb_publishable_"):
            report["supabase"] = {
                "status": "warning",
                "detail": "SUPABASE_KEY looks like a publishable key (sb_publishable_...). "
                          "Use the anon key (starts with eyJ...) from Project Settings > API.",
            }
            logger.warning("SUPABASE_KEY may be wrong format — needs anon key (eyJ...)")
        else:
            report["supabase"] = {"status": "ok", "detail": "URL and key configured"}
    else:
        report["supabase"] = {
            "status": "missing",
            "detail": "SUPABASE_URL and/or SUPABASE_KEY not set. Database features disabled.",
        }
        logger.warning("Supabase not configured — database features will be unavailable")

    # Redis / Upstash
    if s.upstash_redis_rest_url and s.upstash_redis_rest_token:
        report["redis"] = {"status": "ok", "detail": "Upstash Redis configured"}
    else:
        report["redis"] = {
            "status": "missing",
            "detail": "Upstash Redis not configured. Live logs and caching disabled.",
        }

    # LLM / OpenRouter
    if s.openrouter_api_key:
        report["llm"] = {
            "status": "ok",
            "detail": f"OpenRouter configured (primary: {s.llm_primary})",
        }
    else:
        report["llm"] = {
            "status": "missing",
            "detail": "OPENROUTER_API_KEY not set. AI scoring and resume tailoring disabled.",
        }
        logger.warning("OpenRouter not configured — LLM features disabled")

    # Notifications (optional)
    notif_parts = []
    if s.telegram_bot_token and s.telegram_chat_id:
        notif_parts.append("Telegram")
    if s.smtp_email and s.smtp_app_password:
        notif_parts.append("Email")
    if notif_parts:
        report["notifications"] = {
            "status": "ok",
            "detail": f"Configured: {', '.join(notif_parts)}",
        }
    else:
        report["notifications"] = {
            "status": "missing",
            "detail": "No notification channels configured (Telegram/Email).",
        }

    # Applicant profile
    if s.applicant_name != "Your Name" and s.applicant_email != "you@email.com":
        report["profile"] = {"status": "ok", "detail": f"{s.applicant_name} ({s.applicant_email})"}
    else:
        report["profile"] = {
            "status": "warning",
            "detail": "Using default applicant profile. Update APPLICANT_NAME/EMAIL in .env.",
        }

    # Search keywords
    kw = s.keywords_list()
    if kw:
        report["search"] = {"status": "ok", "detail": f"Keywords: {', '.join(kw[:3])}..."}
    else:
        report["search"] = {"status": "warning", "detail": "No SEARCH_KEYWORDS set."}

    # Summary log
    issues = [k for k, v in report.items() if v["status"] != "ok"]
    if issues:
        logger.info("Startup check: {} issue(s) found — {}", len(issues), ", ".join(issues))
    else:
        logger.info("Startup check: all systems configured ✓")

    return report
