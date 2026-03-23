"""Parse user intents and dispatch to agents."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from core.exceptions import LLMError
from core.llm import get_llm_client

INTENT_PROMPT = """You are Jarvis, an AI assistant controlling an autonomous job application agent.
Parse the user message and return ONLY valid JSON with these exact keys:
{
  "intent": "<one of: run_scraper, run_filter, run_resume, run_apply, get_stats, pause_all, resume_all, set_threshold, get_interviews, send_summary, check_ats, send_recruiter_email, interview_questions, linkedin_optimize, resume_variant_best, unknown>",
  "params": { "company": "<optional string>", "job_title": "<optional string>" },
  "reply": "<your friendly response to the user>"
}

Intent guide:
- check_ats: user wants ATS score for a company or role (extract company in params.company)
- send_recruiter_email: user wants outreach to a company (params.company)
- interview_questions: user wants interview prep for a job/company (params.company or job_title)
- linkedin_optimize: optimize LinkedIn headline/profile
- resume_variant_best: which resume A/B variant performs best
"""


async def parse_command(message: str) -> dict:
    """Use LLM to classify user intent."""

    low = message.lower()
    if "which resume variant" in low or "best resume variant" in low or "resume a/b" in low:
        return {
            "intent": "resume_variant_best",
            "params": {},
            "reply": "Checking resume variant performance…",
        }
    if "linkedin" in low and ("headline" in low or "optimize" in low or "profile" in low):
        return {
            "intent": "linkedin_optimize",
            "params": {},
            "reply": "Running LinkedIn optimizer…",
        }
    if "ats" in low and "score" in low:
        m = re.search(r"for\s+([\w\s&.-]+?)(?:\?|$)", message, re.I)
        company = m.group(1).strip() if m else ""
        return {
            "intent": "check_ats",
            "params": {"company": company},
            "reply": f"Checking ATS alignment for {company or 'your latest role'}…",
        }
    if "recruiter" in low and ("email" in low or "outreach" in low or "send" in low):
        m = re.search(r"to\s+([\w\s&.-]+?)(?:\?|$)", message, re.I)
        company = m.group(1).strip() if m else ""
        return {
            "intent": "send_recruiter_email",
            "params": {"company": company},
            "reply": f"Preparing recruiter outreach for {company or 'matching applications'}…",
        }
    if "interview" in low and ("question" in low or "prep" in low):
        m = re.search(r"for\s+([\w\s&.-]+?)(?:\?|$)", message, re.I)
        company = m.group(1).strip() if m else ""
        return {
            "intent": "interview_questions",
            "params": {"company": company},
            "reply": "Generating interview prep…",
        }

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


async def _match_job_and_app(company_fragment: str) -> tuple[dict | None, dict | None]:
    from core.database import get_db_client

    frag = (company_fragment or "").strip().lower()
    db = get_db_client()
    jobs = await db.select("jobs", limit=2000, offset=0)
    apps = await db.select("applications", limit=2000, offset=0)
    job = None
    for j in jobs:
        if frag and frag in (j.get("company") or "").lower():
            job = j
            break
    if not job and jobs:
        job = jobs[0]
    app = None
    if job:
        for a in apps:
            if str(a.get("job_id")) == str(job.get("id")):
                app = a
                break
    return job, app


async def dispatch(intent_dict: dict) -> str:
    """Execute intent and return a short human-readable summary."""

    intent = intent_dict.get("intent", "unknown")
    params = intent_dict.get("params") or {}
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
        if intent == "check_ats":
            from agents.ats_checker import ATSCheckerAgent
            from pathlib import Path

            job, app = await _match_job_and_app(str(params.get("company", "")))
            if not job:
                return "No matching job in pipeline. Scrape and filter first."
            resume_path = Path("resumes/base_resume.txt")
            text = resume_path.read_text(encoding="utf-8") if resume_path.exists() else "Engineer"
            agent = ATSCheckerAgent()
            r = await agent.check_resume(text, str(job.get("description", "") or ""))
            score = r.get("ats_score", 0)
            grade = r.get("overall_grade", "?")
            if app:
                await agent.db.update("applications", app["id"], {"ats_score": int(score)})
            return f"ATS score for {job.get('company')}: {score}% (grade {grade}). Top gaps: {r.get('missing_keywords', [])[:5]}"
        if intent == "send_recruiter_email":
            from agents.recruiter_outreach import RecruiterOutreachAgent
            from core.database import get_db_client

            company = str(params.get("company", ""))
            db = get_db_client()
            apps = await db.select("applications", {"status": "APPLIED"}, limit=100, offset=0)
            agent = RecruiterOutreachAgent()
            profile = (
                f"Name: {agent.settings.applicant_name}\nEmail: {agent.settings.applicant_email}\n"
                f"Years: {agent.settings.years_experience}"
            )
            sent_one = False
            for app in apps:
                if app.get("outreach_sent"):
                    continue
                job = await db.select_one("jobs", {"id": app["job_id"]})
                if not job:
                    continue
                if company and company.lower() not in (job.get("company") or "").lower():
                    continue
                to_email = await agent.find_recruiter_email(job.get("company", ""), job.get("title", ""))
                if not to_email:
                    continue
                gen = await agent.generate_email(job, profile)
                subject = str(gen.get("subject", ""))
                body = str(gen.get("body", "")).replace("\n", "<br/>")
                row = await db.insert(
                    "recruiter_outreach",
                    {
                        "application_id": app["id"],
                        "to_email": to_email,
                        "subject": subject,
                        "body": body,
                    },
                )
                rid = str(row.get("id", uuid.uuid4()))
                if await agent.send_outreach(to_email, subject, body, rid):
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
                    sent_one = True
                    return f"Sent recruiter email to {to_email} for {job.get('company')}."
            return "Sent outreach." if sent_one else "No matching APPLIED application or SMTP not configured."
        if intent == "interview_questions":
            from agents.interview_coach import InterviewCoachAgent
            from core.database import get_db_client

            _job, app = await _match_job_and_app(str(params.get("company", "")))
            if not app:
                apps = await get_db_client().select("applications", limit=50, offset=0)
                app = apps[0] if apps else None
            if not app:
                return "No applications to prep."
            coach = InterviewCoachAgent()
            kit = await coach.create_prep_kit(app["id"])
            q = kit.get("questions") or {}
            beh = (q.get("behavioral") or [])[:2]
            aid = str(app["id"])
            return f"Interview prep saved for application {aid[:8]}…. Sample Q: {beh}"
        if intent == "linkedin_optimize":
            from agents.linkedin_optimizer import LinkedInOptimizerAgent

            agent = LinkedInOptimizerAgent()
            roles = agent.settings.target_roles_list()
            r = await agent.analyze_profile(agent.base_resume or "Engineer", roles)
            heads = r.get("headline_suggestions") or []
            return f"LinkedIn score ~{r.get('score', 0)}. Try headline: {heads[0] if heads else 'n/a'}"
        if intent == "resume_variant_best":
            from agents.resume import ResumeVariantAgent

            perf = await ResumeVariantAgent().analyze_performance()
            w = perf.get("winning_variant")
            pct = perf.get("winning_response_rate_pct", 0)
            return f"Best-performing resume variant so far: {w} (~{pct}% response proxy)."
        return intent_dict.get("reply", "Command noted.")
    except Exception as exc:
        return f"Error executing {intent}: {str(exc)}"
