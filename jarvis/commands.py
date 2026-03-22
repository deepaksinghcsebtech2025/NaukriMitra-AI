"""Parse user intents and dispatch to agents."""

from __future__ import annotations

from core.exceptions import LLMError
from core.llm import get_llm_client

INTENT_PROMPT = """You are Jarvis, an AI assistant controlling an autonomous job application agent.
Parse the user message and return ONLY valid JSON with these exact keys:
{
  "intent": "<one of: run_scraper, run_filter, run_resume, run_apply, get_stats, pause_all, resume_all, set_threshold, get_interviews, send_summary, unknown>",
  "params": {},
  "reply": "<your friendly response to the user>"
}"""


async def parse_command(message: str) -> dict:
    """Use LLM to classify user intent."""

    llm = get_llm_client()
    prompt = f"{INTENT_PROMPT}\n\nUser message: {message}"
    try:
        return await llm.extract_json(prompt, use_cache=False)
    except LLMError as exc:
        return {
            "intent": "unknown",
            "params": {},
            "reply": str(exc),
        }
    except Exception as exc:
        return {
            "intent": "unknown",
            "params": {},
            "reply": (
                "I didn't understand that. Try: 'show stats', 'run scraper', or 'how many applied today?' "
                f"({exc!s})"
            ),
        }


async def dispatch(intent_dict: dict) -> str:
    """Execute intent and return a short human-readable summary."""

    intent = intent_dict.get("intent", "unknown")
    try:
        if intent == "run_scraper":
            from agents.scraper import ScraperAgent

            result = await ScraperAgent().run()
            return f"Scraper done. Found {result.get('new_jobs', 0)} new jobs."
        if intent == "run_filter":
            from agents.filter import FilterAgent

            result = await FilterAgent().run()
            return (
                f"Filter done. {result.get('filtered', 0)} passed, "
                f"{result.get('rejected', 0)} rejected."
            )
        if intent == "run_resume":
            from agents.resume import ResumeAgent

            result = await ResumeAgent().run()
            return f"Resume agent done. {result.get('tailored', 0)} PDFs generated."
        if intent == "run_apply":
            from agents.apply import ApplyAgent

            result = await ApplyAgent().run()
            return f"Apply done. {result.get('applied', 0)} submitted."
        if intent in ("get_stats", "get_interviews"):
            from agents.tracker import TrackerAgent

            stats = await TrackerAgent().get_pipeline_stats()
            return (
                f"Stats: {stats.get('total_jobs', 0)} jobs total | "
                f"Applied today: {stats.get('today_applied', 0)} | "
                f"This week: {stats.get('week_applied', 0)} | "
                f"Interviews: {stats.get('INTERVIEW', 0)} | "
                f"Avg score: {stats.get('avg_match_score', 0)}%"
            )
        if intent == "send_summary":
            from agents.notifier import NotifierAgent

            await NotifierAgent().send_daily_summary()
            return "Daily summary sent to Telegram and email!"
        return intent_dict.get("reply", "Command noted.")
    except Exception as exc:
        return f"Error executing {intent}: {str(exc)}"
