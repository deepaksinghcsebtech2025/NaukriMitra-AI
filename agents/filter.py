"""LLM-based job scoring and application filtering."""

from __future__ import annotations

from pathlib import Path

from agents.base import BaseAgent


class FilterAgent(BaseAgent):
    """Scores DISCOVERED applications and moves them to FILTERED or REJECTED."""

    def __init__(self) -> None:
        """Load base resume text for prompts."""

        super().__init__()
        resume_path = Path("resumes/base_resume.txt")
        self.base_resume = (
            resume_path.read_text(encoding="utf-8")
            if resume_path.exists()
            else "Python developer with backend experience."
        )

    async def score_job(self, job: dict) -> dict:
        """Return structured scores and persist match fields on the job row."""

        prompt = f"""You are a job matching expert. Analyze this job posting against the applicant's resume.
Return ONLY valid JSON with exactly these keys:
{{
  "match_score": <integer 0-100>,
  "reasons": ["reason1", "reason2", "reason3"],
  "skills_gap": ["missing_skill1", "missing_skill2"],
  "tailoring_hints": ["hint1", "hint2", "hint3"],
  "apply_recommended": <true if score >= 70, else false>
}}

Job Title: {job.get('title', '')}
Company: {job.get('company', '')}
Location: {job.get('location', '')}
Description: {str(job.get('description', ''))[:2000]}

Applicant Resume:
{self.base_resume[:1500]}"""

        result = await self.llm.extract_json(prompt, use_cache=True)
        await self.db.update(
            "jobs",
            job["id"],
            {
                "match_score": int(result.get("match_score", 0)),
                "match_reasons": result.get("reasons", []),
                "skills_gap": result.get("skills_gap", []),
                "tailoring_hints": result.get("tailoring_hints", []),
            },
        )
        return result

    async def run(self) -> dict:
        """Score all DISCOVERED applications."""

        await self.log("FilterAgent starting...")
        apps = await self.db.select("applications", {"status": "DISCOVERED"}, limit=100, offset=0)
        await self.log(f"Found {len(apps)} jobs to score")

        filtered = 0
        rejected = 0
        for app in apps:
            try:
                job = await self.db.select_one("jobs", {"id": app["job_id"]})
                if not job:
                    continue
                scores = await self.score_job(job)
                score = int(scores.get("match_score", 0))
                if score >= self.settings.match_threshold:
                    await self.db.update("applications", app["id"], {"status": "FILTERED"})
                    filtered += 1
                else:
                    await self.db.update("applications", app["id"], {"status": "REJECTED"})
                    rejected += 1
                await self.log(f"{job['title']} @ {job['company']} → {score}%")
            except Exception as exc:
                await self.log(f"Score error: {exc}", "warning")

        await self.record_run("completed", filtered + rejected)
        await self.log(f"FilterAgent done. Filtered: {filtered}, Rejected: {rejected}")
        return {"filtered": filtered, "rejected": rejected}
