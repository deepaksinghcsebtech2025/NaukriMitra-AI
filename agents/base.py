"""Base agent with shared clients, logging, and run bookkeeping."""

from __future__ import annotations

from datetime import datetime

from core.cache import get_cache_client
from core.config import get_settings
from core.database import get_db_client
from core.llm import get_llm_client
from core.logger import logger


class BaseAgent:
    """Provides settings, DB, cache, LLM, structured logging, and run records."""

    def __init__(self) -> None:
        """Wire singleton dependencies."""

        self.settings = get_settings()
        self.db = get_db_client()
        self.cache = get_cache_client()
        self.llm = get_llm_client()
        self.started_at = datetime.utcnow()

    async def log(self, msg: str, level: str = "info") -> None:
        """Log to Loguru and Redis log stream."""

        getattr(logger, level, logger.info)(f"[{self.__class__.__name__}] {msg}")
        await self.cache.push_log(f"[{self.__class__.__name__}] {msg}")

    async def record_run(self, status: str, count: int = 0, error: str | None = None) -> None:
        """Persist a row in agent_runs."""

        await self.db.insert(
            "agent_runs",
            {
                "agent_name": self.__class__.__name__,
                "status": status,
                "jobs_processed": count,
                "error_msg": error,
                "started_at": self.started_at.isoformat(),
                "ended_at": datetime.utcnow().isoformat(),
            },
        )

    async def run(self) -> dict:
        """Subclasses implement one agent execution."""

        raise NotImplementedError
