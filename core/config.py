"""Application settings loaded from environment / .env."""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration for NaukriMitra-AI / Ultra Job Agent."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_jwt_secret: str = ""   # Dashboard → Project Settings → API → JWT Settings → JWT Secret
    database_url: str = ""

    # Upstash
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    # OpenRouter
    openrouter_api_key: str = ""
    llm_primary: str = "deepseek/deepseek-chat-v3-0324:free"
    llm_fallback: str = "meta-llama/llama-3.3-70b-instruct:free"

    # Hunter.io (25 free domain searches/month)
    hunter_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Gmail
    smtp_email: str = ""
    smtp_app_password: str = ""

    # Public URL for email tracking pixels (e.g. https://your-app.onrender.com)
    app_public_url: str = ""

    # Applicant
    applicant_name: str = "Your Name"
    applicant_email: str = "you@email.com"
    applicant_phone: str = "+0-000-000-0000"
    applicant_location: str = "City, Country"
    applicant_linkedin: str = ""
    applicant_github: str = ""
    years_experience: int = 3

    # Search
    search_keywords: str = "Python Engineer,Backend Developer"
    search_locations: str = "Remote"
    salary_min_inr: int = 1500000
    match_threshold: int = 75
    max_applications_per_day: int = 15
    scrape_interval_hours: int = 6
    apply_interval_hours: int = 2
    daily_summary_hour: int = 20

    # Smart filters (comma-separated lists in .env)
    exclude_companies: str = ""
    exclude_keywords: str = "unpaid internship only,stipend only"
    min_salary_inr: int = 1500000
    prefer_companies: str = ""
    max_experience_required: int = 10
    work_type: str = "any"
    company_size: str = "any"

    # LinkedIn optimizer target roles (comma-separated)
    target_roles: str = "Software Engineer,Backend Developer"

    # Resume A/B: which variant label to attach on tailor (base | technical | achievement | concise | detailed)
    resume_active_variant: str = "base"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    environment: str = "development"

    def keywords_list(self) -> List[str]:
        """Comma-separated keywords as a list."""

        return [k.strip() for k in self.search_keywords.split(",") if k.strip()]

    def locations_list(self) -> List[str]:
        """Comma-separated locations as a list."""

        return [loc.strip() for loc in self.search_locations.split(",") if loc.strip()]

    def exclude_companies_list(self) -> List[str]:
        return [x.strip().lower() for x in self.exclude_companies.split(",") if x.strip()]

    def exclude_keywords_list(self) -> List[str]:
        return [x.strip().lower() for x in self.exclude_keywords.split(",") if x.strip()]

    def prefer_companies_list(self) -> List[str]:
        return [x.strip().lower() for x in self.prefer_companies.split(",") if x.strip()]

    def target_roles_list(self) -> List[str]:
        return [x.strip() for x in self.target_roles.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""

    return Settings()
