"""Find recruiter emails and send Gmail outreach with optional open tracking."""

from __future__ import annotations

import asyncio
import base64
import re
import smtplib
import uuid
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import httpx

from agents.base import BaseAgent
from core.logger import logger


# Minimal 1x1 transparent GIF for open tracking
_PIXEL_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


class RecruiterOutreachAgent(BaseAgent):
    """Hunter.io (free tier), pattern guess, LLM guess, then Gmail SMTP."""

    async def _hunter_domain_search(self, domain: str) -> Optional[str]:
        key = (self.settings.hunter_api_key or "").strip()
        if not key or not domain:
            return None
        url = "https://api.hunter.io/v2/domain-search"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(url, params={"domain": domain, "api_key": key, "limit": 5})
                if r.status_code != 200:
                    return None
                data = r.json()
                emails = (data.get("data") or {}).get("emails") or []
                for row in emails:
                    e = row.get("value")
                    if e and "@" in e:
                        return str(e).lower()
        except Exception as exc:
            logger.debug("Hunter.io request failed: {}", exc)
        return None

    def _guess_domain(self, company: str) -> str:
        """Heuristic: strip suffixes and build company.com."""

        c = re.sub(r"[^a-zA-Z0-9\s]", "", company or "").strip().lower()
        c = re.sub(r"\s+(inc|llc|ltd|limited|technologies|tech|labs)\s*$", "", c)
        parts = c.split()
        core = parts[0] if parts else "company"
        return f"{core}.com"

    async def find_recruiter_email(self, company: str, job_title: str) -> Optional[str]:
        """Try Hunter domain search, common aliases, then LLM guess."""

        domain = self._guess_domain(company)
        email = await self._hunter_domain_search(domain)
        if email:
            return email

        patterns = [f"hr@{domain}", f"careers@{domain}", f"recruit@{domain}", f"talent@{domain}"]
        for p in patterns:
            if ".." not in p:
                return p

        prompt = f"""Return ONLY valid JSON: {{"email": "<best guess corporate email for recruiting or null>"}}
Company: {company}
Job title: {job_title}
Use a plausible pattern like hr@ or careers@ estimated domain. If unsure, use null."""

        try:
            data = await self.llm.extract_json(prompt, use_cache=True)
            em = data.get("email")
            if em and isinstance(em, str) and "@" in em and "." in em.split("@")[-1]:
                return em.lower().strip()
        except Exception as exc:
            logger.debug("LLM email guess failed: {}", exc)
        return patterns[0]

    async def generate_email(self, job: dict, applicant_profile: dict) -> dict:
        """LLM-generated subject, body, and follow-up."""

        prompt = f"""You write short, human recruiting emails (not AI-sounding).
Return ONLY valid JSON:
{{
  "subject": "Application for {{title}} — {{name}} | {{years}}yr relevant role",
  "body": "Exactly 3 short paragraphs: warm open, 2 concrete achievements with metrics from resume, clear CTA. No 'I am writing to apply'. No 'I believe I would be a great fit'.",
  "follow_up_body": "Brief polite follow-up for ~1 week later, one short paragraph."
}}

Job title: {job.get('title')}
Company: {job.get('company')}
Job summary: {str(job.get('description', ''))[:1200]}

Applicant profile (use real details):
{applicant_profile}"""

        return await self.llm.extract_json(prompt, use_cache=False)

    async def send_outreach(self, to_email: str, subject: str, body: str, outreach_id: str) -> bool:
        """Send HTML email; append tracking pixel if app_public_url set."""

        email = self.settings.smtp_email
        password = self.settings.smtp_app_password
        if not email or not password:
            return False

        base = (self.settings.app_public_url or "").rstrip("/")
        if base:
            pixel = f'<img src="{base}/api/track/open/{outreach_id}" width="1" height="1" alt="" />'
            if "<body" in body.lower():
                body = body.replace("</body>", f"{pixel}</body>", 1)
            else:
                body = body + pixel

        def _send() -> bool:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = email
            msg["To"] = to_email
            msg.attach(MIMEText(body, "html"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(email, password)
                server.sendmail(email, to_email, msg.as_string())
            return True

        try:
            return await asyncio.to_thread(_send)
        except Exception as exc:
            await self.log(f"SMTP outreach failed: {exc}", "warning")
            return False

    async def run(self) -> dict:
        """Outreach for APPLIED applications without prior outreach."""

        await self.log("RecruiterOutreachAgent starting...")
        apps = await self.db.select("applications", {"status": "APPLIED"}, limit=50, offset=0)
        sent = 0
        profile = (
            f"Name: {self.settings.applicant_name}\nEmail: {self.settings.applicant_email}\n"
            f"Phone: {self.settings.applicant_phone}\n"
            f"Years experience: {self.settings.years_experience}\n"
            f"Location: {self.settings.applicant_location}\n"
            f"LinkedIn: {self.settings.applicant_linkedin}\nGitHub: {self.settings.applicant_github}"
        )

        for app in apps:
            if app.get("outreach_sent"):
                continue
            try:
                job = await self.db.select_one("jobs", {"id": app["job_id"]})
                if not job:
                    continue
                to_email = await self.find_recruiter_email(job.get("company", ""), job.get("title", ""))
                if not to_email:
                    continue
                gen = await self.generate_email(job, profile)
                subject = str(gen.get("subject", f"Regarding {job.get('title')}"))
                body_html = str(gen.get("body", "")).replace("\n", "<br/>")
                if not body_html.strip():
                    continue

                oid = str(uuid.uuid4())
                row = await self.db.insert(
                    "recruiter_outreach",
                    {
                        "application_id": app["id"],
                        "to_email": to_email,
                        "subject": subject,
                        "body": body_html,
                    },
                )
                rid = row.get("id", oid)

                ok = await self.send_outreach(to_email, subject, body_html, str(rid))
                if ok:
                    await self.db.update(
                        "applications",
                        app["id"],
                        {
                            "recruiter_email": to_email,
                            "outreach_sent": True,
                            "outreach_sent_at": datetime.utcnow().isoformat(),
                            "outreach_subject": subject,
                        },
                    )
                    await self.db.update(
                        "recruiter_outreach",
                        str(rid),
                        {"sent_at": datetime.utcnow().isoformat()},
                    )
                    sent += 1
                    await self.log(f"Outreach sent to {to_email} for {job.get('company')}")
            except Exception as exc:
                await self.log(f"Outreach error: {exc}", "warning")

        await self.record_run("completed", sent)
        return {"outreach_sent": sent}
