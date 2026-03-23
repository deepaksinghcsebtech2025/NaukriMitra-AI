"""Tailor resume content with LLM and render PDFs with ReportLab."""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from agents.base import BaseAgent


class ResumeAgent(BaseAgent):
    """Generates tailored PDF resumes for FILTERED applications."""

    def __init__(self) -> None:
        """Ensure output directory exists and load base resume."""

        super().__init__()
        resume_path = Path("resumes/base_resume.txt")
        self.base_resume = resume_path.read_text(encoding="utf-8") if resume_path.exists() else ""
        Path("resumes/tailored").mkdir(parents=True, exist_ok=True)

    async def tailor_content(self, job: dict) -> dict:
        """Ask LLM for summary, skills, bullets, and cover letter."""

        hints = job.get("tailoring_hints", [])
        if isinstance(hints, str):
            try:
                hints = json.loads(hints)
            except json.JSONDecodeError:
                hints = []

        prompt = f"""You are an expert resume writer. Tailor this resume for the specific job below.
Return ONLY valid JSON with exactly these keys:
{{
  "summary": "3-sentence professional summary tailored to this role",
  "skills": ["skill1", "skill2", ... up to 12 skills],
  "experience_bullets": [
    "5 achievement bullets using STAR; include metrics from the resume where possible",
    ...
  ],
  "cover_letter": "A single string: exactly 3 paragraphs, 250-300 words total. Paragraph 1: specific hook about THIS company and role (research from description). Paragraph 2: your top 2-3 wins with metrics pulled from the resume text. Paragraph 3: confident call to action. Tone: direct and human. FORBIDDEN phrases: 'I am writing to apply', 'I believe I would be a great fit', 'Dear Hiring Manager' as lazy filler. No generic AI fluff."
}}

Target Job: {job.get('title')} at {job.get('company')}
Location: {job.get('location')}
Description: {str(job.get('description', ''))[:2000]}
Tailoring hints: {hints}

Applicant Resume:
{self.base_resume[:2000]}"""

        return await self.llm.extract_json(prompt, use_cache=False)

    async def generate_pdf(self, content: dict, job: dict, output_path: str) -> str:
        """Build a one-page style PDF with header, summary, skills, experience."""

        cfg = self.settings
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )
        accent = colors.HexColor("#2563eb")
        dark = colors.HexColor("#1a1a2e")

        name_style = ParagraphStyle(
            "Name",
            fontSize=22,
            textColor=dark,
            fontName="Helvetica-Bold",
            spaceAfter=4,
        )
        contact_style = ParagraphStyle(
            "Contact",
            fontSize=9,
            textColor=colors.gray,
            fontName="Helvetica",
            spaceAfter=8,
        )
        section_style = ParagraphStyle(
            "Section",
            fontSize=11,
            textColor=accent,
            fontName="Helvetica-Bold",
            spaceBefore=10,
            spaceAfter=4,
        )
        body_style = ParagraphStyle(
            "Body",
            fontSize=9.5,
            fontName="Helvetica",
            leading=14,
            spaceAfter=3,
        )
        bullet_style = ParagraphStyle(
            "Bullet",
            fontSize=9.5,
            fontName="Helvetica",
            leading=13,
            leftIndent=10,
            spaceAfter=2,
        )

        story: list = []

        story.append(Paragraph(cfg.applicant_name, name_style))
        contact_line = f"{cfg.applicant_email} | {cfg.applicant_phone} | {cfg.applicant_location}"
        if cfg.applicant_linkedin:
            contact_line += f" | {cfg.applicant_linkedin}"
        if cfg.applicant_github:
            contact_line += f" | {cfg.applicant_github}"
        story.append(Paragraph(contact_line, contact_style))
        story.append(HRFlowable(width="100%", thickness=1.5, color=accent, spaceAfter=8))

        story.append(Paragraph("PROFESSIONAL SUMMARY", section_style))
        story.append(Paragraph(content.get("summary", ""), body_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=4))

        story.append(Paragraph("TECHNICAL SKILLS", section_style))
        skills = content.get("skills", [])
        mid = (len(skills) + 1) // 2
        col1 = "<br/>".join(f"• {sk}" for sk in skills[:mid])
        col2 = "<br/>".join(f"• {sk}" for sk in skills[mid:])
        skill_table = Table(
            [[Paragraph(col1, body_style), Paragraph(col2, body_style)]],
            colWidths=["50%", "50%"],
        )
        skill_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story.append(skill_table)
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=4))

        story.append(Paragraph("PROFESSIONAL EXPERIENCE", section_style))
        for bullet in content.get("experience_bullets", []):
            story.append(Paragraph(str(bullet), bullet_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey, spaceAfter=4))

        footer_style = ParagraphStyle(
            "Footer",
            fontSize=8,
            textColor=colors.gray,
            fontName="Helvetica-Oblique",
            alignment=1,
        )
        story.append(Spacer(1, 10))
        story.append(
            Paragraph(
                f"Tailored for {job.get('company', '')} — {job.get('title', '')}",
                footer_style,
            )
        )

        doc.build(story)
        return output_path

    async def run(self) -> dict:
        """Tailor resumes for FILTERED applications."""

        await self.log("ResumeAgent starting...")
        apps = await self.db.select("applications", {"status": "FILTERED"}, limit=50, offset=0)
        await self.log(f"Found {len(apps)} applications to tailor")

        count = 0
        for app in apps:
            try:
                job = await self.db.select_one("jobs", {"id": app["job_id"]})
                if not job:
                    continue
                content = await self.tailor_content(job)
                output_path = f"resumes/tailored/{job['id']}.pdf"
                await self.generate_pdf(content, job, output_path)
                await self.db.update(
                    "applications",
                    app["id"],
                    {
                        "status": "TAILORED",
                        "resume_path": output_path,
                        "cover_letter": content.get("cover_letter", ""),
                        "resume_variant": self.settings.resume_active_variant,
                    },
                )
                count += 1
                await self.log(f"Tailored: {job['title']} @ {job['company']}")
            except Exception as exc:
                await self.log(f"Resume error: {exc}", "warning")

        await self.record_run("completed", count)
        await self.log(f"ResumeAgent done. {count} PDFs generated.")
        return {"tailored": count}


class ResumeVariantAgent(BaseAgent):
    """Generate alternate resume text files per style and summarize variant performance."""

    STYLES = ("technical", "achievement", "concise", "detailed")

    async def create_variant(self, base_resume: str, style: str) -> str:
        """Rewrite resume in the given style; persist to disk and resume_variants table."""

        if style not in self.STYLES:
            raise ValueError(f"style must be one of {self.STYLES}")
        prompt = f"""Rewrite the resume below in a '{style}' style.
Return ONLY valid JSON: {{"content": "<full plain-text resume body>"}}

Rules:
- technical: emphasize stack, system design, depth
- achievement: emphasize metrics, outcomes, leadership
- concise: shorter sections, punchy bullets
- detailed: richer context per role

Original resume:
{base_resume[:4000]}"""

        data = await self.llm.extract_json(prompt, use_cache=False)
        text = str(data.get("content", "")).strip()
        Path("resumes/variants").mkdir(parents=True, exist_ok=True)
        out_path = Path(f"resumes/variants/{style}_resume.txt")
        out_path.write_text(text, encoding="utf-8")

        await self.db.insert(
            "resume_variants",
            {"variant_name": style, "content": text[:50000]},
        )
        return str(out_path)

    async def analyze_performance(self) -> dict:
        """Aggregate applications by resume_variant; proxy 'response' with interview-stage counts."""

        apps = await self.db.select("applications", limit=10000, offset=0)
        by_variant: dict[str, dict[str, int]] = {}
        for a in apps:
            v = (a.get("resume_variant") or "base").lower()
            if v not in by_variant:
                by_variant[v] = {"total": 0, "responses": 0}
            by_variant[v]["total"] += 1
            if a.get("status") in ("INTERVIEW", "OFFER", "REVIEWING", "SUBMITTED"):
                by_variant[v]["responses"] += 1

        winner = None
        best_rate = -1.0
        for v, m in by_variant.items():
            rate = (m["responses"] / m["total"] * 100) if m["total"] else 0.0
            if rate > best_rate:
                best_rate = rate
                winner = v

        return {
            "by_variant": by_variant,
            "winning_variant": winner,
            "winning_response_rate_pct": round(best_rate, 2) if winner else 0.0,
        }

    async def run(self) -> dict:
        """Generate all style variants from base resume."""

        base = Path("resumes/base_resume.txt")
        text = base.read_text(encoding="utf-8") if base.exists() else ""
        if not text.strip():
            return {"variants": 0, "error": "base_resume.txt missing"}
        n = 0
        for style in self.STYLES:
            try:
                await self.create_variant(text, style)
                n += 1
            except Exception as exc:
                await self.log(f"Variant {style} failed: {exc}", "warning")
        await self.record_run("completed", n)
        return {"variants": n}
