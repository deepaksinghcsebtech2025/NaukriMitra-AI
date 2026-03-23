"""LinkedIn profile optimization suggestions from resume and target roles."""

from __future__ import annotations

from pathlib import Path

from agents.base import BaseAgent


class LinkedInOptimizerAgent(BaseAgent):
    """LLM-driven headline, summary, skills, and content ideas."""

    def __init__(self) -> None:
        super().__init__()
        resume_path = Path("resumes/base_resume.txt")
        self.base_resume = (
            resume_path.read_text(encoding="utf-8")
            if resume_path.exists()
            else ""
        )

    async def analyze_profile(self, resume_text: str, target_roles: list[str]) -> dict:
        """Return structured LinkedIn optimization payload."""

        roles = ", ".join(target_roles[:8])
        prompt = f"""You are a LinkedIn branding expert. Return ONLY valid JSON:
{{
  "headline_suggestions": ["3 headline options, max 220 chars each"],
  "summary_rewrite": "About section, 2-3 short paragraphs, keyword-rich",
  "skills_to_add": ["8-12 skills to feature"],
  "keywords_missing": ["keywords to weave in from target roles"],
  "connection_strategy": "2-3 sentences: who to connect with and why",
  "post_ideas": ["3 post ideas relevant to target roles"],
  "score": <integer 0-100 profile strength estimate>
}}

Target roles: {roles}

Resume:
{resume_text[:3500]}"""

        return await self.llm.extract_json(prompt, use_cache=True)

    async def run(self) -> dict:
        """Log-only batch run hook (primary use is API)."""

        roles = self.settings.target_roles_list()
        result = await self.analyze_profile(self.base_resume or "Engineer", roles)
        await self.log(f"LinkedIn optimizer score: {result.get('score', 0)}")
        await self.record_run("completed", 1)
        return {"linkedin_score": result.get("score", 0)}
