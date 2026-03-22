"""Domain-specific exceptions for the Ultra Job Agent."""


class AgentError(Exception):
    """Base class for agent-related failures."""

    pass


class LLMError(AgentError):
    """LLM or JSON parsing failures."""

    pass


class ScraperError(AgentError):
    """Scraper or parsing failures."""

    pass


class DBError(AgentError):
    """Database operation failures."""

    pass


class RateLimitError(AgentError):
    """External rate limiting."""

    pass


class CaptchaError(AgentError):
    """CAPTCHA detected during apply flow."""

    pass


class ManualReviewRequired(AgentError):
    """Human review needed before continuing."""

    pass
