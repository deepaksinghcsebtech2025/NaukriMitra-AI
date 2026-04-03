"""Playwright-based application form submission with retry and error recovery."""

from __future__ import annotations

import asyncio
import random
from datetime import date, datetime
from pathlib import Path

from playwright.async_api import async_playwright

from agents.base import BaseAgent
from core.exceptions import CaptchaError
from core.resume_parser import get_parsed_resume


class ApplyAgent(BaseAgent):
    """Submits TAILORED applications up to the daily quota."""

    FIELD_PATTERNS = {
        # Contact
        "name":       ["name", "full_name", "fullname", "your_name", "applicant", "candidate_name", "applicant_name"],
        "email":      ["email", "e-mail", "email_address", "contact_email", "your_email"],
        "phone":      ["phone", "mobile", "telephone", "contact_number", "phone_number", "mobile_number"],
        "linkedin":   ["linkedin", "linkedin_url", "linkedin_profile", "linkedin_link"],
        "github":     ["github", "github_url", "portfolio", "website", "personal_website", "portfolio_url"],
        "location":   ["location", "city", "current_location", "address", "current_city", "residing"],
        # Resume content
        "cover":      ["cover", "cover_letter", "coverletter", "message", "why_us",
                       "motivation", "additional_info", "why_interested", "about_yourself",
                       "tell_us", "introduction", "personal_statement"],
        "years_exp":  ["years_experience", "years_exp", "experience_years", "total_experience",
                       "years_of_experience", "work_experience"],
        "skills":     ["skills", "technical_skills", "key_skills", "core_skills",
                       "technologies", "tech_stack", "expertise"],
        "summary":    ["summary", "profile_summary", "professional_summary", "about_me",
                       "bio", "objective", "career_objective"],
        "degree":     ["degree", "qualification", "highest_qualification", "education",
                       "highest_degree", "academic_qualification"],
        "university": ["university", "college", "institution", "school", "institute"],
        "curr_title": ["current_title", "current_role", "job_title", "designation",
                       "current_designation", "role", "position"],
        "salary_exp": ["expected_salary", "salary_expectation", "ctc_expected",
                       "expected_ctc", "salary", "compensation"],
        "notice":     ["notice_period", "notice", "joining_date", "available_from",
                       "availability", "when_can_join"],
    }

    MAX_RETRIES = 2

    async def fill_field(self, page, key: str, value: str) -> bool:
        """Try several selectors for a logical field group."""
        for pattern in self.FIELD_PATTERNS.get(key, []):
            selectors = [
                f'input[name*="{pattern}" i]',
                f'input[placeholder*="{pattern}" i]',
                f'input[id*="{pattern}" i]',
                f'input[autocomplete*="{pattern}" i]',
                f'textarea[name*="{pattern}" i]',
                f'textarea[placeholder*="{pattern}" i]',
                f'textarea[id*="{pattern}" i]',
            ]
            for sel in selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=800):
                        await el.click()
                        await el.fill(value)
                        return True
                except Exception:
                    continue
        return False

    async def _try_apply(self, job: dict, application: dict, resume_path: str) -> dict:
        """Single attempt to open apply URL, fill fields, and submit."""

        # Load parsed resume once for this attempt
        parsed = get_parsed_resume()

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        try:
            apply_url = job.get("apply_url", "")
            if not apply_url:
                return {"status": "FAILED", "error": "No apply URL"}

            await page.goto(apply_url, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2500)

            content = (await page.content()).lower()
            if any(w in content for w in ["captcha", "robot", "verify you", "i'm not a robot", "recaptcha"]):
                raise CaptchaError("CAPTCHA detected on application page")

            s = self.settings

            # --- Basic contact fields (prefer resume data, fall back to .env) ---
            await self.fill_field(page, "name",     parsed.name or s.applicant_name)
            await self.fill_field(page, "email",    parsed.email or s.applicant_email)
            await self.fill_field(page, "phone",    parsed.phone or s.applicant_phone)
            await self.fill_field(page, "linkedin", parsed.linkedin or s.applicant_linkedin or "")
            await self.fill_field(page, "github",   parsed.github or s.applicant_github or "")
            await self.fill_field(page, "location", parsed.location or s.applicant_location)

            # --- Experience ---
            exp_years = parsed.experience_years or s.years_experience
            await self.fill_field(page, "years_exp", str(int(exp_years)))

            # --- Resume-enriched fields ---
            if parsed.skills_text:
                await self.fill_field(page, "skills", parsed.skills_text)

            if parsed.summary:
                await self.fill_field(page, "summary", parsed.summary)

            if parsed.education_text:
                # Fill degree field with first degree line if available
                degree_line = parsed.education[0]["degree"] if parsed.education else parsed.education_text[:100]
                await self.fill_field(page, "degree", degree_line)
                await self.fill_field(page, "university", parsed.education_text[:150])

            if parsed.current_title:
                await self.fill_field(page, "curr_title", parsed.current_title)

            # Salary expectation from .env
            if s.salary_min_inr:
                salary_lpa = round(s.salary_min_inr / 100000, 1)
                await self.fill_field(page, "salary_exp", str(salary_lpa))

            # Notice period: default 30 days / immediate for fresher
            await self.fill_field(page, "notice", "30 days" if exp_years >= 1 else "Immediate")

            # Cover letter
            cover = application.get("cover_letter", "")
            if cover:
                await self.fill_field(page, "cover", cover)

            # Resume file upload
            if resume_path and Path(resume_path).exists():
                try:
                    file_input = page.locator('input[type="file"]').first
                    if await file_input.is_visible(timeout=2000):
                        await file_input.set_input_files(resume_path)
                        await page.wait_for_timeout(1200)
                except Exception:
                    pass

            # Submit
            submit_selectors = [
                'button:has-text("Submit Application")',
                'button:has-text("Submit")',
                'button:has-text("Apply Now")',
                'button:has-text("Apply")',
                'button:has-text("Send Application")',
                'button:has-text("Continue")',
                'input[type="submit"]',
                'button[type="submit"]',
            ]
            submitted = False
            for sel in submit_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=800):
                        await btn.click()
                        submitted = True
                        await page.wait_for_timeout(3000)
                        break
                except Exception:
                    continue

            if not submitted:
                return {"status": "MANUAL_REVIEW", "error": "Could not find submit button"}

            final_content = (await page.content()).lower()
            success_signals = [
                "thank you", "application submitted", "successfully applied",
                "we received", "application complete", "you applied",
                "application received", "we'll be in touch", "submitted successfully",
            ]
            if any(sig in final_content for sig in success_signals):
                return {"status": "APPLIED"}

            return {"status": "MANUAL_REVIEW", "error": "No confirmation detected"}

        except CaptchaError:
            raise
        except Exception as exc:
            return {"status": "FAILED", "error": str(exc)[:300]}
        finally:
            await context.close()
            await browser.close()
            await playwright.stop()

    async def apply_to_job(self, job: dict, application: dict, resume_path: str) -> dict:
        """Apply with up to MAX_RETRIES attempts on transient failures."""
        last_result = {"status": "FAILED", "error": "No attempts made"}
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = await self._try_apply(job, application, resume_path)
                if result["status"] != "FAILED":
                    return result
                last_result = result
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(3 * attempt)
            except CaptchaError:
                raise
            except Exception as exc:
                last_result = {"status": "FAILED", "error": str(exc)[:300]}
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(3 * attempt)
        return last_result

    async def run(self) -> dict:
        """Apply to TAILORED jobs until daily cap."""

        await self.log("ApplyAgent starting...")

        # Count today's applications
        today_count = 0
        all_apps = await self.db.select("applications", limit=10000, offset=0)
        today = date.today().isoformat()
        for a in all_apps:
            if (a.get("applied_at") or "")[:10] == today and a["status"] in ("APPLIED", "SUBMITTED"):
                today_count += 1

        remaining = self.settings.max_applications_per_day - today_count
        if remaining <= 0:
            await self.log(f"Daily limit reached ({self.settings.max_applications_per_day})")
            return {"applied": 0, "reason": "daily_limit_reached"}

        apps = await self.db.select("applications", {"status": "TAILORED"}, limit=remaining, offset=0)
        await self.log(f"Found {len(apps)} to apply. Remaining quota: {remaining}")

        applied = 0
        failed = 0
        manual = 0

        for app in apps:
            try:
                job = await self.db.select_one("jobs", {"id": app["job_id"]})
                if not job:
                    continue

                resume_path = app.get("resume_path", "")
                if not resume_path or not Path(resume_path).exists():
                    await self.log(
                        f"Skipping {job.get('title')} — resume file missing: {resume_path}", "warning"
                    )
                    continue

                await self.log(f"Applying: {job['title']} @ {job['company']}")
                result = await self.apply_to_job(job, app, resume_path)
                status = result["status"]

                update_data: dict = {
                    "status": status,
                    "applied_at": datetime.utcnow().isoformat(),
                }
                if result.get("error"):
                    update_data["error_msg"] = result["error"]

                await self.db.update("applications", app["id"], update_data)

                if status == "APPLIED":
                    applied += 1
                elif status == "FAILED":
                    failed += 1
                else:
                    manual += 1

                try:
                    from agents.notifier import NotifierAgent
                    await NotifierAgent().notify_application(job, app, status)
                except Exception:
                    pass

                await self.log(f"{status}: {job['title']} @ {job['company']}")
                # Human-like delay between applications
                await asyncio.sleep(random.uniform(8, 20))

            except CaptchaError:
                await self.db.update(
                    "applications",
                    app["id"],
                    {"status": "MANUAL_REVIEW", "error_msg": "CAPTCHA detected — manual action needed"},
                )
                manual += 1
                await self.log(f"CAPTCHA hit on {app.get('job_id')} — marked MANUAL_REVIEW", "warning")
            except Exception as exc:
                await self.log(f"Apply error: {exc}", "warning")
                failed += 1

        await self.record_run("completed", applied)
        await self.log(f"ApplyAgent done. Applied: {applied}, Manual: {manual}, Failed: {failed}")
        return {"applied": applied, "manual_review": manual, "failed": failed}
