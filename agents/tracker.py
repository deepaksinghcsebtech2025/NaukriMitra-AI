"""Application pipeline state machine and aggregate stats."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from agents.base import BaseAgent
from core.exceptions import AgentError


class TrackerAgent(BaseAgent):
    """Validates status transitions and aggregates pipeline metrics."""

    VALID_TRANSITIONS = {
        "DISCOVERED": ["FILTERED", "REJECTED"],
        "FILTERED": ["TAILORED", "REJECTED"],
        "TAILORED": ["APPLIED", "MANUAL_REVIEW", "FAILED", "REJECTED"],
        "APPLIED": ["SUBMITTED", "FAILED", "REJECTED"],
        "MANUAL_REVIEW": ["APPLIED", "REJECTED"],
        "SUBMITTED": ["REVIEWING", "REJECTED"],
        "REVIEWING": ["INTERVIEW", "REJECTED"],
        "INTERVIEW": ["OFFER", "REJECTED"],
        "OFFER": ["ACCEPTED", "REJECTED"],
    }

    async def transition(self, application_id: str, to_state: str, reason: str = "") -> dict:
        """Move an application to a new status if allowed."""

        app = await self.db.select_one("applications", {"id": application_id})
        if not app:
            raise AgentError(f"Application {application_id} not found")
        from_state = app["status"]
        allowed = self.VALID_TRANSITIONS.get(from_state, [])
        if to_state not in allowed:
            raise AgentError(f"Invalid transition: {from_state} → {to_state}")
        updated = await self.db.update("applications", application_id, {"status": to_state})
        await self.db.insert(
            "state_log",
            {
                "application_id": application_id,
                "from_state": from_state,
                "to_state": to_state,
                "reason": reason,
            },
        )
        return updated

    async def get_pipeline_stats(self) -> dict:
        """Count applications by status plus derived KPIs."""

        apps = await self.db.select("applications", limit=10000, offset=0)
        stats: dict[str, int] = {}
        for app in apps:
            st = app["status"]
            stats[st] = stats.get(st, 0) + 1

        today = date.today().isoformat()
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()

        today_applied = 0
        week_applied = 0
        for a in apps:
            applied_raw = a.get("applied_at") or ""
            applied_day = applied_raw[:10] if applied_raw else ""
            if a["status"] in ("APPLIED", "SUBMITTED") and applied_day == today:
                today_applied += 1
            if a["status"] in ("APPLIED", "SUBMITTED") and applied_day >= week_ago:
                week_applied += 1

        jobs = await self.db.select("jobs", limit=10000, offset=0)
        scored = [j for j in jobs if j.get("match_score", 0) > 0]
        avg_score = round(sum(j["match_score"] for j in scored) / len(scored)) if scored else 0

        return {
            **stats,
            "today_applied": today_applied,
            "week_applied": week_applied,
            "avg_match_score": avg_score,
            "total_jobs": len(jobs),
        }

    async def run(self) -> dict:
        """Log current pipeline stats (manual / diagnostic)."""

        stats = await self.get_pipeline_stats()
        await self.log(f"Pipeline stats: {stats}")
        return stats
