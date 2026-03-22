"""Playwright-based application form submission."""

from __future__ import annotations

import asyncio
import random
from datetime import date, datetime

from playwright.async_api import async_playwright

from agents.base import BaseAgent
from core.exceptions import CaptchaError


class ApplyAgent(BaseAgent):
    """Submits TAILORED applications up to the daily quota."""

    FIELD_PATTERNS = {
        "name": ["name", "full_name", "fullname", "your_name", "applicant"],
        "email": ["email", "e-mail", "email_address"],
        "phone": ["phone", "mobile", "telephone", "contact_number"],
        "linkedin": ["linkedin", "linkedin_url", "linkedin_profile"],
        "github": ["github", "github_url", "portfolio", "website"],
        "location": ["location", "city", "current_location", "address"],
        "cover": ["cover", "cover_letter", "coverletter", "message", "why_us", "motivation"],
    }

    async def fill_field(self, page, key: str, value: str) -> bool:
        """Try several selectors for a logical field group."""

        for pattern in self.FIELD_PATTERNS.get(key, []):
            selectors = [
                f'input[name*="{pattern}" i]',
                f'input[placeholder*="{pattern}" i]',
                f'input[id*="{pattern}" i]',
                f'textarea[name*="{pattern}" i]',
                f'textarea[placeholder*="{pattern}" i]',
            ]
            for sel in selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=1000):
                        await el.fill(value)
                        return True
                except Exception as exc:
                    _ = exc
                    continue
        return False

    async def apply_to_job(self, job: dict, application: dict, resume_path: str) -> dict:
        """Open apply URL, fill best-effort fields, upload resume, submit."""

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        try:
            apply_url = job.get("apply_url", "")
            if not apply_url:
                return {"status": "FAILED", "error": "No apply URL"}

            await page.goto(apply_url, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            content = (await page.content()).lower()
            if any(w in content for w in ["captcha", "robot", "verify you", "i'm not a robot"]):
                raise CaptchaError("CAPTCHA detected on application page")

            s = self.settings
            await self.fill_field(page, "name", s.applicant_name)
            await self.fill_field(page, "email", s.applicant_email)
            await self.fill_field(page, "phone", s.applicant_phone)
            await self.fill_field(page, "linkedin", s.applicant_linkedin)
            await self.fill_field(page, "github", s.applicant_github)
            await self.fill_field(page, "location", s.applicant_location)
            cover = application.get("cover_letter", "")
            if cover:
                await self.fill_field(page, "cover", cover)

            try:
                file_input = page.locator('input[type="file"]').first
                if await file_input.is_visible(timeout=2000):
                    await file_input.set_input_files(resume_path)
                    await page.wait_for_timeout(1000)
            except Exception as exc:
                _ = exc

            submit_selectors = [
                'button:has-text("Submit")',
                'button:has-text("Apply Now")',
                'button:has-text("Apply")',
                'button:has-text("Send Application")',
                'input[type="submit"]',
                'button[type="submit"]',
            ]
            submitted = False
            for sel in submit_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        submitted = True
                        break
                except Exception as exc:
                    _ = exc
                    continue

            if not submitted:
                return {"status": "MANUAL_REVIEW", "error": "Could not find submit button"}

            await page.wait_for_timeout(3000)
            final_content = (await page.content()).lower()
            success_signals = [
                "thank you",
                "application submitted",
                "successfully applied",
                "we received",
                "application complete",
                "you applied",
            ]
            if any(sig in final_content for sig in success_signals):
                return {"status": "APPLIED"}
            return {"status": "MANUAL_REVIEW", "error": "No confirmation detected"}

        except CaptchaError:
            raise
        except Exception as exc:
            return {"status": "FAILED", "error": str(exc)}
        finally:
            await context.close()
            await browser.close()
            await playwright.stop()

    async def run(self) -> dict:
        """Apply to TAILORED jobs until daily cap."""

        await self.log("ApplyAgent starting...")

        today_count = 0
        all_apps = await self.db.select("applications", limit=10000, offset=0)
        today = date.today().isoformat()
        for a in all_apps:
            if (
                (a.get("applied_at") or "")[:10] == today
                and a["status"] in ("APPLIED", "SUBMITTED")
            ):
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
                if not resume_path:
                    continue

                result = await self.apply_to_job(job, app, resume_path)
                status = result["status"]
                update_data = {
                    "status": status,
                    "applied_at": datetime.utcnow().isoformat(),
                    "error_msg": result.get("error"),
                }
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
                except Exception as exc:
                    _ = exc

                await self.log(f"{status}: {job['title']} @ {job['company']}")
                await asyncio.sleep(random.uniform(5, 15))

            except CaptchaError:
                await self.db.update(
                    "applications",
                    app["id"],
                    {"status": "MANUAL_REVIEW", "error_msg": "CAPTCHA detected"},
                )
                manual += 1
            except Exception as exc:
                await self.log(f"Apply error: {exc}", "warning")
                failed += 1

        await self.record_run("completed", applied)
        await self.log(f"ApplyAgent done. Applied: {applied}, Manual: {manual}, Failed: {failed}")
        return {"applied": applied, "manual_review": manual, "failed": failed}
