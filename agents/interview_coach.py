"""Interview preparation: questions and STAR-style answers from resume + job."""

from __future__ import annotations

import json
from pathlib import Path

from agents.base import BaseAgent


class InterviewCoachAgent(BaseAgent):
    """Generates categorized interview questions and tailored answers."""

    def __init__(self) -> None:
        super().__init__()
        resume_path = Path("resumes/base_resume.txt")
        self.base_resume = (
            resume_path.read_text(encoding="utf-8")
            if resume_path.exists()
            else "Software engineer with shipping experience."
        )

    async def generate_questions(self, job: dict) -> dict:
        """Produce structured interview questions for the role."""

        prompt = f"""You are a hiring manager. Return ONLY valid JSON:
{{
  "behavioral": ["4 behavioral interview questions"],
  "technical": ["3 technical questions for this stack"],
  "situational": ["2 situational questions"],
  "company_specific": ["1 question about motivation for this company"]
}}

Job title: {job.get('title')}
Company: {job.get('company')}
Description: {str(job.get('description', ''))[:2500]}"""

        return await self.llm.extract_json(prompt, use_cache=True)

    async def generate_answers(self, questions: list[str], resume_text: str) -> list[dict]:
        """STAR-style answers for each question."""

        out: list[dict] = []
        batch = questions[:12]
        for q in batch:
            prompt = f"""Return ONLY valid JSON: {{"answer": "STAR-format answer 4-6 sentences", "tips": "one interview tip"}}
Interview question: {q}
Resume context:
{resume_text[:2000]}"""
            try:
                row = await self.llm.extract_json(prompt, use_cache=False)
                out.append({"question": q, "answer": row.get("answer", ""), "tips": row.get("tips", "")})
            except Exception as exc:
                await self.log(f"Answer gen skip: {exc}", "warning")
                out.append({"question": q, "answer": "", "tips": ""})
        return out

    async def create_prep_kit(self, application_id: str) -> dict:
        """Build full prep kit and persist on the application row."""

        app = await self.db.select_one("applications", {"id": application_id})
        if not app:
            raise ValueError("application not found")
        job = await self.db.select_one("jobs", {"id": app["job_id"]})
        if not job:
            raise ValueError("job not found")

        qset = await self.generate_questions(job)
        flat: list[str] = []
        for k in ("behavioral", "technical", "situational", "company_specific"):
            for item in qset.get(k, []) or []:
                if isinstance(item, str):
                    flat.append(item)

        answers = await self.generate_answers(flat, self.base_resume)
        kit = {
            "questions": qset,
            "qa": answers,
            "company": job.get("company"),
            "title": job.get("title"),
        }
        await self.db.update(
            "applications",
            application_id,
            {"interview_prep": kit},
        )
        return kit

    async def run(self) -> dict:
        """Generate prep kits for FILTERED applications missing interview_prep."""

        await self.log("InterviewCoachAgent starting...")
        apps = await self.db.select("applications", {"status": "FILTERED"}, limit=30, offset=0)
        n = 0
        for app in apps:
            prep = app.get("interview_prep")
            if isinstance(prep, str):
                try:
                    prep = json.loads(prep) if prep.strip() else {}
                except json.JSONDecodeError:
                    prep = {}
            if not isinstance(prep, dict):
                prep = {}
            if prep.get("questions"):
                continue
            try:
                await self.create_prep_kit(app["id"])
                n += 1
            except Exception as exc:
                await self.log(f"Prep kit error: {exc}", "warning")

        await self.record_run("completed", n)
        return {"prep_kits": n}
