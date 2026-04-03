"""LLM-based job scoring, smart pre-filters, and match explainer."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from agents.base import BaseAgent


_SERVICE_COS = ("tcs", "wipro", "infosys", "cognizant", "capgemini", "accenture", "hcl", "tech mahindra")


class FilterAgent(BaseAgent):
    """Scores DISCOVERED applications and moves them to FILTERED or REJECTED."""

    def __init__(self) -> None:
        super().__init__()
        resume_path = Path("resumes/base_resume.txt")
        self.base_resume = (
            resume_path.read_text(encoding="utf-8")
            if resume_path.exists()
            else "Python developer with backend experience."
        )

    def _prefilter_job(self, job: dict) -> tuple[bool, str]:
        """Return (should_reject, reason) before LLM."""

        s = self.settings
        company = (job.get("company") or "").strip().lower()
        title = (job.get("title") or "").lower()
        desc = (job.get("description") or "").lower()
        blob = f"{title} {desc}"

        for ex in s.exclude_companies_list():
            if ex and ex in company:
                return True, f"excluded_company:{ex}"

        for kw in s.exclude_keywords_list():
            if kw and kw in blob:
                return True, f"excluded_keyword:{kw}"

        min_lpa = int(s.min_salary_inr) / 100000.0
        salary_patterns = re.findall(
            r"(\d+(?:\.\d+)?)\s*[-–]?\s*(\d+(?:\.\d+)?)?\s*(lpa|lakhs?|lac)", blob, re.I
        )
        for a, b, _u in salary_patterns[:3]:
            try:
                hi = float(b) if b else float(a)
                if hi * 100000 < int(s.min_salary_inr) and hi < min_lpa * 2:
                    if hi * 100000 < int(s.min_salary_inr) * 0.5:
                        return True, "salary_below_threshold"
            except ValueError:
                continue

        exp_m = re.search(r"(\d+)\s*[-–]?\s*(\d+)?\s*\+?\s*years?", blob)
        if exp_m:
            try:
                req = int(exp_m.group(2) or exp_m.group(1))
                if req > int(s.max_experience_required):
                    return True, "experience_above_max"
            except ValueError:
                pass

        return False, ""

    def _score_adjustments(self, job: dict, base_score: int) -> int:
        """Apply work-type and service-company tweaks."""

        s = self.settings
        score = max(0, min(100, int(base_score)))
        company = (job.get("company") or "").lower()
        desc = (job.get("description") or "").lower()

        if any(c in company for c in _SERVICE_COS):
            score = max(0, score - 20)

        wt = (s.work_type or "any").lower()
        if wt == "remote" and "remote" in desc:
            score = min(100, score + 10)
        elif wt == "hybrid" and "hybrid" in desc:
            score = min(100, score + 10)
        elif wt == "onsite" and "on-site" in desc or "onsite" in desc:
            score = min(100, score + 10)

        for pref in s.prefer_companies_list():
            if pref and (pref in company or pref in desc):
                score = min(100, score + 5)
                break

        return score

    async def score_job(self, job: dict) -> dict:
        """Return structured scores and persist extended job fields."""

        reject, reason = self._prefilter_job(job)
        if reject:
            await self.db.update(
                "jobs",
                job["id"],
                {
                    "match_score": 0,
                    "match_reasons": [reason],
                    "red_flags": [reason],
                    "match_explanation": "Filtered out before scoring.",
                    "why_apply": "",
                    "salary_estimate": "",
                },
            )
            return {
                "match_score": 0,
                "reasons": [reason],
                "skills_gap": [],
                "tailoring_hints": [],
                "apply_recommended": False,
                "match_explanation": "Did not pass smart filters.",
                "why_apply": "",
                "red_flags": [reason],
                "salary_estimate": "N/A",
                "prefilter_rejected": True,
            }

        prompt = f"""You are a senior technical recruiter matching candidates to jobs.
Score this job against the applicant's resume across 5 dimensions.

Return ONLY valid JSON:
{{
  "match_score": <integer 0-100, weighted average of dimension scores>,
  "dimension_scores": {{
    "skills_alignment": <0-100 — do their tech skills match requirements?>,
    "experience_level": <0-100 — does their seniority match the JD level?>,
    "domain_relevance": <0-100 — industry/domain overlap?>,
    "location_fit":     <0-100 — location/remote match?>,
    "growth_potential": <0-100 — is this a good career move?>
  }},
  "reasons": ["top 3 reasons this is a good match"],
  "skills_gap": ["skills mentioned in JD that the applicant lacks"],
  "tailoring_hints": ["3 specific tips to tailor the resume for this job"],
  "apply_recommended": <true if match_score >= 70>,
  "match_explanation": "2-sentence plain-English summary of fit.",
  "why_apply": "One compelling specific reason to apply (company, tech, growth).",
  "red_flags": ["any concerns: location mismatch, over-qualified, startup risk, etc."],
  "salary_estimate": "Estimated India CTC '15-22 LPA' from context, or 'Unknown'",
  "ats_keywords": ["top 8 keywords from JD to include in resume for ATS"]
}}

Job Title: {job.get('title', '')}
Company: {job.get('company', '')}
Location: {job.get('location', '')}
Source: {job.get('source', '')}
Description:
{str(job.get('description', ''))[:2500]}

Applicant Resume:
{self.base_resume[:1800]}"""

        result = await self.llm.extract_json(prompt, use_cache=True)
        raw_score = int(result.get("match_score", 0))
        score = self._score_adjustments(job, raw_score)
        result["match_score"] = score

        await self.db.update(
            "jobs",
            job["id"],
            {
                "match_score": score,
                "match_reasons": result.get("reasons", []),
                "skills_gap": result.get("skills_gap", []),
                "tailoring_hints": result.get("tailoring_hints", []),
                "match_explanation": str(result.get("match_explanation", ""))[:2000],
                "why_apply": str(result.get("why_apply", ""))[:1000],
                "red_flags": result.get("red_flags", []),
                "salary_estimate": str(result.get("salary_estimate", ""))[:500],
                "ats_keywords": result.get("ats_keywords", []),
            },
        )
        result["prefilter_rejected"] = False
        return result

    async def _process_app(self, app: dict) -> tuple[str, int]:
        """Score one application; return (new_status, score)."""
        job = await self.db.select_one("jobs", {"id": app["job_id"]})
        if not job:
            return "REJECTED", 0
        scores = await self.score_job(job)
        score = int(scores.get("match_score", 0))
        pre_reject = bool(scores.get("prefilter_rejected"))
        if pre_reject or score < self.settings.match_threshold:
            new_status = "REJECTED"
        else:
            new_status = "FILTERED"
        await self.db.update("applications", app["id"], {"status": new_status})
        await self.log(f"{job['title']} @ {job['company']} → {score}% → {new_status}")
        return new_status, score

    async def run(self) -> dict:
        """Score all DISCOVERED applications (up to 5 concurrent LLM calls)."""

        await self.log("FilterAgent starting...")
        apps = await self.db.select("applications", {"status": "DISCOVERED"}, limit=150, offset=0)
        await self.log(f"Found {len(apps)} jobs to score")

        filtered = 0
        rejected = 0
        errors = 0

        # Process in batches of 5 to avoid rate-limiting
        BATCH = 5
        for i in range(0, len(apps), BATCH):
            batch = apps[i: i + BATCH]
            tasks = [self._process_app(app) for app in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    await self.log(f"Score error: {res}", "warning")
                    errors += 1
                else:
                    status, _ = res
                    if status == "FILTERED":
                        filtered += 1
                    else:
                        rejected += 1
            # Small pause between batches to respect rate limits
            if i + BATCH < len(apps):
                await asyncio.sleep(1)

        await self.record_run("completed", filtered + rejected)
        await self.log(f"FilterAgent done. Filtered: {filtered}, Rejected: {rejected}, Errors: {errors}")
        return {"filtered": filtered, "rejected": rejected, "errors": errors}
