"""Register periodic jobs on application lifespan."""

from __future__ import annotations

import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.config import get_settings
from core.logger import logger

_scheduler: AsyncIOScheduler | None = None


def reset_scheduler() -> None:
    """Stop and drop the global scheduler (used by tests and clean shutdown)."""

    global _scheduler
    if _scheduler is not None:
        try:
            if _scheduler.running:
                _scheduler.shutdown(wait=False)
        except Exception as exc:
            logger.debug("scheduler shutdown in reset: {}", exc)
        _scheduler = None


async def run_scrape_and_filter() -> None:
    """Run scraper then filter with error isolation."""

    start = time.perf_counter()
    try:
        from agents.filter import FilterAgent
        from agents.scraper import ScraperAgent

        logger.info("Scheduler: starting scrape+filter")
        await ScraperAgent().run()
        await FilterAgent().run()
        logger.info("Scheduler: scrape+filter complete in {:.1f}s", time.perf_counter() - start)
    except Exception as exc:
        logger.error("Scheduler scrape error: {}", exc)


async def run_resume_and_apply() -> None:
    """Tailor resumes then submit applications."""

    start = time.perf_counter()
    try:
        from agents.apply import ApplyAgent
        from agents.resume import ResumeAgent

        logger.info("Scheduler: starting resume+apply")
        await ResumeAgent().run()
        await ApplyAgent().run()
        logger.info("Scheduler: resume+apply complete in {:.1f}s", time.perf_counter() - start)
    except Exception as exc:
        logger.error("Scheduler apply error: {}", exc)


async def run_daily_summary() -> None:
    """Send Telegram/email summary."""

    try:
        from agents.notifier import NotifierAgent

        await NotifierAgent().send_daily_summary()
    except Exception as exc:
        logger.error("Scheduler summary error: {}", exc)


async def run_cleanup() -> None:
    """Delete stale agent_runs rows."""

    try:
        from core.database import get_db_client

        db = get_db_client()
        await db.delete_agent_runs_older_than_days(30)
        logger.info("Cleanup: removed agent_runs older than 30 days")
    except Exception as exc:
        logger.error("Cleanup error: {}", exc)


def get_scheduler() -> AsyncIOScheduler:
    """Singleton AsyncIO scheduler with default jobs."""

    global _scheduler
    if _scheduler is None:
        s = get_settings()
        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(
            run_scrape_and_filter,
            IntervalTrigger(hours=s.scrape_interval_hours),
            id="scrape_filter",
            replace_existing=True,
        )
        _scheduler.add_job(
            run_resume_and_apply,
            IntervalTrigger(hours=s.apply_interval_hours),
            id="resume_apply",
            replace_existing=True,
        )
        _scheduler.add_job(
            run_daily_summary,
            CronTrigger(hour=s.daily_summary_hour, minute=0),
            id="daily_summary",
            replace_existing=True,
        )
        _scheduler.add_job(
            run_cleanup,
            CronTrigger(hour=3, minute=0),
            id="cleanup",
            replace_existing=True,
        )
    return _scheduler
