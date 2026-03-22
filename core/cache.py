"""Upstash Redis REST cache: logs, config overrides, LLM cache keys."""

from __future__ import annotations

import asyncio
from typing import Optional

from upstash_redis import Redis

from core.config import get_settings
from core.logger import logger


class CacheClient:
    """Thin async wrapper around Upstash Redis (sync SDK via asyncio.to_thread)."""

    def __init__(self) -> None:
        """Initialize REST client from settings."""

        settings = get_settings()
        url = (settings.upstash_redis_rest_url or "").strip()
        token = (settings.upstash_redis_rest_token or "").strip()
        self.is_configured: bool = bool(url and token and url.startswith("http"))

        if self.is_configured:
            self._redis = Redis(url=url, token=token)
        else:
            self._redis = None
            logger.debug(
                "Upstash Redis not configured; cache and live log tail disabled. "
                "Set UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN to enable."
            )

    async def get(self, key: str) -> Optional[str]:
        """Return string value or None."""

        if not self.is_configured or self._redis is None:
            return None
        return await asyncio.to_thread(self._redis.get, key)

    async def set(self, key: str, value: str, ttl_seconds: int = 3600) -> bool:
        """Set key with TTL; return True on success."""

        if not self.is_configured or self._redis is None:
            return False

        def _set() -> bool:
            try:
                self._redis.set(key, value, ex=ttl_seconds)
                return True
            except Exception as exc:  # pragma: no cover - network
                logger.debug("Redis set failed: {}", exc)
                return False

        return await asyncio.to_thread(_set)

    async def delete(self, key: str) -> bool:
        """Delete key; return True if removed."""

        if not self.is_configured or self._redis is None:
            return False

        def _del() -> bool:
            try:
                n = self._redis.delete(key)
                return bool(n)
            except Exception as exc:  # pragma: no cover
                logger.debug("Redis delete failed: {}", exc)
                return False

        return await asyncio.to_thread(_del)

    async def push_log(self, message: str) -> None:
        """Prepend log line and trim to last 200 entries (or loguru only if Redis off)."""

        if not self.is_configured or self._redis is None:
            logger.debug("{}", message)
            return

        def _push() -> None:
            try:
                self._redis.lpush("agent:logs", message)
                self._redis.ltrim("agent:logs", 0, 199)
            except Exception as exc:  # pragma: no cover
                logger.debug("Redis push_log failed: {}", exc)

        await asyncio.to_thread(_push)

    async def get_logs(self, n: int = 50) -> list[str]:
        """Return last n log lines (newest first)."""

        if not self.is_configured or self._redis is None:
            return []

        def _range() -> list[str]:
            try:
                raw = self._redis.lrange("agent:logs", 0, max(0, n - 1))
                if not raw:
                    return []
                return [str(x) for x in raw]
            except Exception as exc:  # pragma: no cover
                logger.debug("Redis get_logs failed: {}", exc)
                return []

        return await asyncio.to_thread(_range)


_cache_client: Optional[CacheClient] = None


def get_cache_client() -> CacheClient:
    """Lazy singleton for cache access."""

    global _cache_client
    if _cache_client is None:
        _cache_client = CacheClient()
    return _cache_client
