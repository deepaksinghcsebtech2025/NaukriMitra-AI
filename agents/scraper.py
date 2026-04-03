"""Playwright scrapers for LinkedIn, Indeed, Naukri, and Glassdoor."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from agents.base import BaseAgent
from core.salary import detect_remote_type, estimate_salary, extract_experience_range


class ScraperAgent(BaseAgent):
    """Discover jobs from public search pages and persist to Supabase."""

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def _job_hash(self, company: str, title: str) -> str:
        """Stable short hash for external_id composition."""

        return hashlib.sha256(f"{company.lower()}{title.lower()}".encode()).hexdigest()[:16]

    @staticmethod
    def _slug(text: str) -> str:
        """URL slug for Naukri-style paths."""

        s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").lower()).strip("-")
        return s or "jobs"

    async def _get_page(self):
        """Launch Playwright Chromium with a realistic viewport."""

        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=self.USER_AGENT,
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        return playwright, browser, context, page

    async def scrape_linkedin(self, keywords: str, location: str, max_results: int = 20) -> list:
        """Scrape LinkedIn job search results (best-effort selectors)."""

        playwright = None
        browser = None
        jobs: list[dict] = []
        try:
            playwright, browser, context, page = await self._get_page()
            url = (
                f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(keywords)}"
                f"&location={quote_plus(location)}&sortBy=DD"
            )
            await page.goto(url, timeout=60000)
            await page.wait_for_timeout(3000)
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)
            cards = await page.query_selector_all(
                ".job-search-results__list-item, .jobs-search__results-list li, li.jobs-search-results__list-item"
            )
            for card in cards[:max_results]:
                try:
                    title_el = await card.query_selector(
                        ".job-card-list__title, .base-search-card__title, h3"
                    )
                    company_el = await card.query_selector(
                        ".job-card-container__primary-description, .base-search-card__subtitle, h4"
                    )
                    location_el = await card.query_selector(
                        ".job-card-container__metadata-item, .job-search-card__location"
                    )
                    link_el = await card.query_selector("a.job-card-list__title, a.base-card__full-link, a")
                    if not title_el or not company_el:
                        continue
                    title = (await title_el.inner_text()).strip()
                    company = (await company_el.inner_text()).strip()
                    location_text = (await location_el.inner_text()).strip() if location_el else location
                    href = await link_el.get_attribute("href") if link_el else ""
                    job_id = self._job_hash(company, title)
                    apply_url = href.split("?")[0] if href else ""
                    jobs.append(
                        {
                            "external_id": f"li_{job_id}",
                            "title": title,
                            "company": company,
                            "location": location_text,
                            "apply_url": apply_url,
                            "source": "linkedin",
                        }
                    )
                except Exception as exc:
                    _ = exc
                    continue
        finally:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
        return jobs

    async def scrape_indeed(self, keywords: str, location: str, max_results: int = 20) -> list:
        """Scrape Indeed India job cards."""

        playwright = None
        browser = None
        jobs: list[dict] = []
        try:
            playwright, browser, context, page = await self._get_page()
            url = (
                f"https://in.indeed.com/jobs?q={quote_plus(keywords)}&l={quote_plus(location)}&sort=date"
            )
            await page.goto(url, timeout=60000)
            await page.wait_for_timeout(3000)
            cards = await page.query_selector_all(".job_seen_beacon, .tapItem")
            for card in cards[:max_results]:
                try:
                    title_el = await card.query_selector(".jobTitle span, .jcs-JobTitle span")
                    company_el = await card.query_selector(".companyName, [data-testid='company-name']")
                    location_el = await card.query_selector(".companyLocation, [data-testid='text-location']")
                    link_el = await card.query_selector("a.jcs-JobTitle, a[data-jk]")
                    if not title_el or not company_el:
                        continue
                    title = (await title_el.inner_text()).strip()
                    company = (await company_el.inner_text()).strip()
                    location_text = (await location_el.inner_text()).strip() if location_el else location
                    href = await link_el.get_attribute("href") if link_el else ""
                    full_url = f"https://in.indeed.com{href}" if href and href.startswith("/") else href
                    job_id = self._job_hash(company, title)
                    jobs.append(
                        {
                            "external_id": f"in_{job_id}",
                            "title": title,
                            "company": company,
                            "location": location_text,
                            "apply_url": full_url or "",
                            "source": "indeed",
                        }
                    )
                except Exception as exc:
                    _ = exc
                    continue
        finally:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
        return jobs

    async def scrape_naukri(self, keywords: str, location: str, max_results: int = 30) -> list:
        """Scrape Naukri.com job listing (best-effort; layout may change)."""

        playwright = None
        browser = None
        jobs: list[dict] = []
        kw_slug = self._slug(keywords.split(",")[0] if keywords else "jobs")
        loc_slug = self._slug(location)
        try:
            playwright, browser, context, page = await self._get_page()
            url = f"https://www.naukri.com/{kw_slug}-jobs-in-{loc_slug}"
            await page.goto(url, timeout=90000, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)
            await page.wait_for_selector("div.jobTuple, article.jobTuple, .cust-job-tuple", timeout=15000)
            cards = await page.query_selector_all("div.jobTuple, article.jobTuple, .cust-job-tuple")
            for card in cards[:max_results]:
                try:
                    title_el = await card.query_selector(".title a, a.title, h2.title a")
                    company_el = await card.query_selector(".subTitle, .comp-name, span.subTitle")
                    loc_el = await card.query_selector(".location, .locWdth")
                    exp_el = await card.query_selector(".experience, .expwdth")
                    sal_el = await card.query_selector(".salary, .salary-snippet")
                    if not title_el:
                        continue
                    title = (await title_el.inner_text()).strip()
                    company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                    loc_txt = (await loc_el.inner_text()).strip() if loc_el else location
                    exp_txt = (await exp_el.inner_text()).strip() if exp_el else ""
                    sal_txt = (await sal_el.inner_text()).strip() if sal_el else ""
                    href = await title_el.get_attribute("href") if title_el else ""
                    if href and not href.startswith("http"):
                        href = f"https://www.naukri.com{href}" if href.startswith("/") else href
                    jid = self._job_hash(company, title)
                    desc_bits = [exp_txt, sal_txt, loc_txt]
                    jobs.append(
                        {
                            "external_id": f"nk_{jid}",
                            "title": title,
                            "company": company,
                            "location": loc_txt,
                            "apply_url": href or url,
                            "source": "naukri",
                            "description": " ".join(x for x in desc_bits if x),
                        }
                    )
                except Exception as exc:
                    _ = exc
                    continue
        finally:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
        return jobs

    async def scrape_glassdoor(self, keywords: str, location: str, max_results: int = 20) -> list:
        """Scrape Glassdoor India job search (best-effort)."""

        playwright = None
        browser = None
        jobs: list[dict] = []
        q = quote_plus(keywords)
        try:
            playwright, browser, context, page = await self._get_page()
            url = f"https://www.glassdoor.co.in/Job/jobs.htm?sc.keyword={q}"
            await page.goto(url, timeout=90000, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
            cards = await page.query_selector_all(
                "li.react-job-listing, div[data-test='job-listing'], .JobCard"
            )
            if not cards:
                cards = await page.query_selector_all("article")
            for card in cards[:max_results]:
                try:
                    title_el = await card.query_selector(
                        "a.jobLink, a[data-test='job-link'], h2 a, .jobTitle a"
                    )
                    company_el = await card.query_selector(
                        ".employerName, [data-test='employer-name'], .jobCard__company"
                    )
                    loc_el = await card.query_selector(
                        ".location, [data-test='job-location'], .jobCard__location"
                    )
                    if not title_el:
                        continue
                    title = (await title_el.inner_text()).strip()
                    company = (await company_el.inner_text()).strip() if company_el else "Unknown"
                    loc_txt = (await loc_el.inner_text()).strip() if loc_el else location
                    href = await title_el.get_attribute("href") if title_el else ""
                    if href and href.startswith("/"):
                        href = f"https://www.glassdoor.co.in{href}"
                    jid = self._job_hash(company, title)
                    jobs.append(
                        {
                            "external_id": f"gd_{jid}",
                            "title": title,
                            "company": company,
                            "location": loc_txt,
                            "apply_url": href or url,
                            "source": "glassdoor",
                        }
                    )
                except Exception as exc:
                    _ = exc
                    continue
        finally:
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
        return jobs

    async def fetch_description(self, url: str) -> str:
        """Fetch job page text for LLM scoring (truncated)."""

        if not url:
            return ""
        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=True,
                headers={"User-Agent": self.USER_AGENT},
            ) as client:
                resp = await client.get(url)
                soup = BeautifulSoup(resp.text, "lxml")
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()
                return soup.get_text(separator=" ", strip=True)[:3000]
        except Exception as exc:
            _ = exc
            return ""

    def _enrich_job(self, job: dict, description: str) -> dict:
        """Add salary, experience, remote_type from description text."""
        text = description or job.get("description", "")

        sal = estimate_salary(text)
        if sal["min"]:
            job["salary_min"] = sal["min"]
        if sal["max"]:
            job["salary_max"] = sal["max"]
        if sal["raw"]:
            job["salary_estimate"] = sal["raw"]

        exp = extract_experience_range(text)
        if exp["min"] is not None:
            job["experience_min"] = exp["min"]
        if exp["max"] is not None:
            job["experience_max"] = exp["max"]

        # detect remote type from location + description combined
        combined = f"{job.get('location', '')} {text}"
        job["remote_type"] = detect_remote_type(combined)

        return job

    async def deduplicate(self, jobs: list) -> list:
        """Drop jobs whose external_id already exists in the database.

        Also performs fuzzy dedup: jobs with the same title+company are
        flagged as duplicates (keeps whichever was scraped first this run).
        """
        if not jobs:
            return []

        # Fetch existing external_ids from DB
        existing_ids: set[str] = set()
        existing = await self.db.select("jobs", limit=10000, offset=0)
        for j in existing:
            existing_ids.add(j["external_id"])

        seen_ids: set[str] = set()
        seen_title_company: set[str] = set()
        result: list[dict] = []

        for j in jobs:
            eid = j["external_id"]
            if eid in existing_ids or eid in seen_ids:
                continue
            # Fuzzy dedup: same normalised title + company
            fuzzy_key = f"{j.get('title','').lower().strip()}|{j.get('company','').lower().strip()}"
            if fuzzy_key in seen_title_company:
                continue
            seen_ids.add(eid)
            seen_title_company.add(fuzzy_key)
            result.append(j)

        return result

    async def run(self) -> dict:
        """Scrape all keyword/location pairs, save new jobs and DISCOVERED applications."""

        await self.log("ScraperAgent starting...")
        all_jobs: list[dict] = []
        for keyword in self.settings.keywords_list():
            for location in self.settings.locations_list():
                await self.log(f"Scraping: {keyword} in {location}")
                try:
                    li_jobs = await self.scrape_linkedin(keyword, location)
                    await self.log(f"LinkedIn: {len(li_jobs)} found")
                    all_jobs.extend(li_jobs)
                except Exception as exc:
                    await self.log(f"LinkedIn error: {exc}", "warning")
                try:
                    in_jobs = await self.scrape_indeed(keyword, location)
                    await self.log(f"Indeed: {len(in_jobs)} found")
                    all_jobs.extend(in_jobs)
                except Exception as exc:
                    await self.log(f"Indeed error: {exc}", "warning")
                try:
                    nk = await self.scrape_naukri(keyword, location)
                    await self.log(f"Naukri: {len(nk)} found")
                    all_jobs.extend(nk)
                except Exception as exc:
                    await self.log(f"Naukri error: {exc}", "warning")
                try:
                    gd = await self.scrape_glassdoor(keyword, location)
                    await self.log(f"Glassdoor: {len(gd)} found")
                    all_jobs.extend(gd)
                except Exception as exc:
                    await self.log(f"Glassdoor error: {exc}", "warning")

        new_jobs = await self.deduplicate(all_jobs)
        await self.log(f"New unique jobs after dedup: {len(new_jobs)} (from {len(all_jobs)} scraped)")

        saved = 0
        for job in new_jobs:
            try:
                desc = await self.fetch_description(job.get("apply_url", ""))
                job["description"] = desc
                # Enrich with salary / experience / remote_type
                job = self._enrich_job(job, desc)
                inserted = await self.db.insert("jobs", job)
                await self.db.insert(
                    "applications",
                    {
                        "job_id": inserted["id"],
                        "status": "DISCOVERED",
                    },
                )
                saved += 1
            except Exception as exc:
                await self.log(f"Save error for {job.get('title')}: {exc}", "warning")

        await self.record_run("completed", saved)
        await self.log(f"ScraperAgent done. Saved {saved} new jobs.")
        return {"new_jobs": saved, "total_scraped": len(all_jobs)}
