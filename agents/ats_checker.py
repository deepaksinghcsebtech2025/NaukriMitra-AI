"""ATS-style resume vs job description checker using LLM."""

from __future__ import annotations

import json
from pathlib import Path

from agents.base import BaseAgent


class ATSCheckerAgent(BaseAgent):
    """Scores resume text against a job description for keyword and format hints."""

    def __init__(self) -> None:
        super().__init__()
        resume_path = Path("resumes/base_resume.txt")
        self.base_resume = (
            resume_path.read_text(encoding="utf-8")
            if resume_path.exists()
            else "Experienced software engineer."
        )

    async def check_resume(self, resume_text: str, job_description: str) -> dict:
        """Return structured ATS analysis with sub-scores."""

        prompt = f"""You are a senior ATS and technical recruiting expert. Analyze resume vs job description.

Return ONLY valid JSON:
{{
  "ats_score": <integer 0-100, overall ATS compatibility>,
  "sub_scores": {{
    "keyword_match": <0-100, % of JD keywords present in resume>,
    "skills_coverage": <0-100, technical skills alignment>,
    "experience_format": <0-100, resume structure/readability for ATS>,
    "quantified_impact": <0-100, has measurable achievements with numbers>
  }},
  "missing_keywords": ["critical JD keyword missing from resume — max 10"],
  "present_keywords": ["strong matching keyword found — max 10"],
  "format_issues": ["specific ATS-unfriendly formatting issue"],
  "improvements": ["concrete, specific improvement with example"],
  "overall_grade": "A" | "B" | "C" | "D",
  "quick_wins": ["1-line change to instantly improve score — max 3"]
}}

Job description:
{job_description[:3000]}

Resume:
{resume_text[:3000]}"""

        return await self.llm.extract_json(prompt, use_cache=True)

    async def run(self) -> dict:
        """Run ATS check for FILTERED applications and persist ats_score."""

        await self.log("ATSCheckerAgent starting...")
        apps = await self.db.select("applications", {"status": "FILTERED"}, limit=100, offset=0)
        checked = 0
        for app in apps:
            try:
                job = await self.db.select_one("jobs", {"id": app["job_id"]})
                if not job:
                    continue
                desc = str(job.get("description", "") or "")
                result = await self.check_resume(self.base_resume, desc)
                score = int(result.get("ats_score", 0))
                await self.db.update(
                    "applications",
                    app["id"],
                    {"ats_score": score},
                )
                kw = result.get("present_keywords", []) + result.get("missing_keywords", [])
                await self.db.update(
                    "jobs",
                    job["id"],
                    {"ats_keywords": kw[:30] if isinstance(kw, list) else []},
                )
                checked += 1
                await self.log(f"ATS {score}% for {job.get('title')} @ {job.get('company')}")
            except Exception as exc:
                await self.log(f"ATS check error: {exc}", "warning")

        await self.record_run("completed", checked)
        return {"checked": checked}
