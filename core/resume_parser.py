"""Resume parser — extracts structured profile data from uploaded resume text.

Used by ApplyAgent to fill job application forms with accurate resume-based values
instead of just the basic .env settings.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from core.logger import logger

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_SKILL_SECTIONS = re.compile(
    r"(?:skills?|technical skills?|core competencies|technologies|stack|tools?)"
    r"\s*[:\-–]?\s*\n?(.*?)(?=\n[A-Z][A-Z]|\Z)",
    re.IGNORECASE | re.DOTALL,
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+91[\s\-]?)?[6-9]\d{9}")
_LINKEDIN_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[\w\-]+/?", re.IGNORECASE)
_GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/[\w\-]+/?", re.IGNORECASE)

_DEGREE_KEYWORDS = [
    "b.tech", "b.e.", "bachelor", "b.sc", "bsc", "bca",
    "m.tech", "m.e.", "master", "m.sc", "msc", "mca", "mba",
    "ph.d", "phd", "diploma",
]

_EXPERIENCE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:experience|exp)",
    re.IGNORECASE,
)

_SECTION_HEADERS = re.compile(
    r"^(experience|work experience|employment|education|skills?|projects?|"
    r"certifications?|summary|objective|profile|achievements?|awards?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ParsedResume:
    """Structured data extracted from a plain-text resume."""

    def __init__(self) -> None:
        self.name: str = ""
        self.email: str = ""
        self.phone: str = ""
        self.linkedin: str = ""
        self.github: str = ""
        self.location: str = ""
        self.summary: str = ""
        self.skills: list[str] = []
        self.skills_text: str = ""          # comma-separated, ready for form fields
        self.education: list[dict] = []     # [{degree, institution, year}]
        self.education_text: str = ""
        self.experience_years: Optional[float] = None
        self.current_title: str = ""
        self.companies: list[str] = []
        self.raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "linkedin": self.linkedin,
            "github": self.github,
            "location": self.location,
            "summary": self.summary,
            "skills": self.skills,
            "skills_text": self.skills_text,
            "education": self.education,
            "education_text": self.education_text,
            "experience_years": self.experience_years,
            "current_title": self.current_title,
            "companies": self.companies,
        }


def parse_resume(text: str) -> ParsedResume:
    """Parse plain-text resume content into a structured ParsedResume object."""

    result = ParsedResume()
    result.raw_text = text
    lines = [l.rstrip() for l in text.splitlines()]
    non_empty = [l for l in lines if l.strip()]

    # --- Name: heuristic — first non-empty line that looks like a name ------
    for line in non_empty[:5]:
        stripped = line.strip()
        # Skip lines with URLs, @, digits-only, or very long lines
        if (
            "@" not in stripped
            and "http" not in stripped
            and len(stripped.split()) in (2, 3, 4)
            and not re.search(r"\d{5,}", stripped)
            and stripped == stripped  # always True, kept for readability
        ):
            result.name = stripped
            break

    # --- Contact fields ---------------------------------------------------
    email_m = _EMAIL_RE.search(text)
    if email_m:
        result.email = email_m.group()

    phone_m = _PHONE_RE.search(text)
    if phone_m:
        raw_phone = phone_m.group().replace(" ", "").replace("-", "")
        if not raw_phone.startswith("+91"):
            raw_phone = "+91" + raw_phone
        result.phone = raw_phone

    linkedin_m = _LINKEDIN_RE.search(text)
    if linkedin_m:
        result.linkedin = linkedin_m.group().rstrip("/")

    github_m = _GITHUB_RE.search(text)
    if github_m:
        result.github = github_m.group().rstrip("/")

    # --- Location: look for city / state patterns -------------------------
    location_patterns = [
        r"(?:bangalore|bengaluru|mumbai|delhi|hyderabad|pune|chennai|kolkata|"
        r"noida|gurgaon|gurugram|remote|india)[,\s]*(?:[a-z\s]+)?(?:india)?",
    ]
    for pat in location_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result.location = m.group().strip().title()
            break

    # --- Skills -----------------------------------------------------------
    skills_raw = _extract_section(text, [
        "skills", "technical skills", "core competencies",
        "technologies", "stack", "tools",
    ])
    if skills_raw:
        # Split on common delimiters
        skill_tokens = re.split(r"[,|•·\n]+", skills_raw)
        skills = [
            s.strip().strip("–-•·*")
            for s in skill_tokens
            if 1 < len(s.strip()) < 50
            and not re.match(r"^(skills?|technologies|tools?)\s*:?\s*$", s.strip(), re.IGNORECASE)
        ]
        result.skills = [s for s in skills if s]
        result.skills_text = ", ".join(result.skills[:20])

    # --- Experience years -------------------------------------------------
    exp_m = _EXPERIENCE_RE.search(text)
    if exp_m:
        result.experience_years = float(exp_m.group(1))

    # --- Education --------------------------------------------------------
    edu_raw = _extract_section(text, ["education", "academic", "qualification"])
    if edu_raw:
        result.education_text = edu_raw[:400].strip()
        # Find degree lines
        for line in edu_raw.splitlines():
            lower = line.lower()
            if any(kw in lower for kw in _DEGREE_KEYWORDS):
                year_m = re.search(r"\b(20\d{2}|19\d{2})\b", line)
                result.education.append({
                    "degree": line.strip(),
                    "year": year_m.group() if year_m else "",
                })

    # --- Summary / Objective ----------------------------------------------
    summary_raw = _extract_section(text, ["summary", "objective", "profile", "about"])
    if summary_raw:
        result.summary = " ".join(summary_raw.split())[:500]

    # --- Current title: look for common job titles near the top -----------
    title_patterns = [
        r"(?:software|backend|full.?stack|frontend|python|senior|junior|lead|"
        r"principal|staff)\s+(?:engineer|developer|architect|programmer)",
        r"(?:engineer|developer|architect)\s*(?:–|-|,)?\s*(?:python|backend|full.?stack|java)?",
    ]
    for pat in title_patterns:
        m = re.search(pat, "\n".join(non_empty[:20]), re.IGNORECASE)
        if m:
            result.current_title = m.group().strip()
            break

    logger.debug(
        "Parsed resume: name={}, skills={}, edu={}, exp_years={}",
        result.name, len(result.skills), len(result.education), result.experience_years,
    )
    return result


def _extract_section(text: str, headings: list[str]) -> str:
    """Extract text under a section heading until the next heading."""

    heading_pat = "|".join(re.escape(h) for h in headings)
    pattern = re.compile(
        rf"(?:^|\n)(?:{heading_pat})\s*[:\-–]?\s*\n(.*?)(?=\n(?:[A-Z][A-Za-z ]+[:\-–]?\s*\n)|$)",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# File loader — reads base_resume.txt or the latest upload
# ---------------------------------------------------------------------------

def load_resume_text(base_dir: Optional[str] = None) -> str:
    """Load resume text from resumes/base_resume.txt (or latest upload)."""

    if base_dir is None:
        base_dir = str(Path(__file__).resolve().parents[1] / "resumes")

    base = Path(base_dir) / "base_resume.txt"
    if base.exists() and base.stat().st_size > 0:
        return base.read_text(encoding="utf-8", errors="ignore")

    # Fallback: newest upload
    uploads = sorted(
        Path(base_dir).glob("uploads/*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for f in uploads:
        if f.suffix.lower() in (".txt", ".pdf", ".docx", ".md"):
            try:
                return f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

    return ""


def get_parsed_resume(base_dir: Optional[str] = None) -> ParsedResume:
    """Convenience: load and parse in one call."""
    text = load_resume_text(base_dir)
    if not text:
        logger.warning("No resume text found — using empty ParsedResume")
        return ParsedResume()
    return parse_resume(text)
