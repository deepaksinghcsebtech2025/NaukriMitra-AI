"""Supabase PostgREST client with async-friendly wrappers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from supabase import Client, create_client

from core.config import get_settings
from core.exceptions import DBError
from core.logger import logger

# Keywords that indicate a network/DNS/connectivity failure (not a data error).
_CONN_ERROR_HINTS = (
    "nodename nor servname",
    "name or service not known",
    "connecterror",
    "connection refused",
    "network is unreachable",
    "timed out",
    "connect timeout",
    "errno 8",
    "getaddrinfo",
)


def _is_connection_error(exc: Exception) -> bool:
    """Return True if the exception looks like a network/DNS failure."""
    msg = str(exc).lower()
    return any(hint in msg for hint in _CONN_ERROR_HINTS)


class DBClient:
    """Thin async wrapper around sync supabase-py (executes in a thread pool)."""

    def __init__(self) -> None:
        """Create Supabase client from URL and anon/service key."""

        settings = get_settings()
        url = settings.supabase_url or "https://placeholder.supabase.co"
        key = settings.supabase_key or "placeholder-anon-key"
        if not settings.supabase_url or not settings.supabase_key:
            logger.warning(
                "Supabase URL or key missing — using placeholder client. "
                "Set SUPABASE_URL and SUPABASE_KEY in .env"
            )
        self.client: Client = create_client(url, key)
        self._configured: bool = bool(settings.supabase_url and settings.supabase_key)
        # Set to True after first confirmed connection error to suppress repeated noise.
        self._unreachable: bool = False

    async def insert(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        """Insert one row; return first row from response."""

        if not self._configured:
            raise DBError("Supabase is not configured — set SUPABASE_URL and SUPABASE_KEY in .env")
        if self._unreachable:
            raise DBError(
                "Supabase is unreachable — project may be paused. "
                "Visit https://supabase.com/dashboard to unpause it."
            )

        def _run() -> dict[str, Any]:
            response = self.client.table(table).insert(data).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
            raise DBError(f"Insert returned no data for table {table}")

        try:
            result = await asyncio.to_thread(_run)
            self._unreachable = False
            return result
        except DBError:
            raise
        except Exception as exc:
            if _is_connection_error(exc):
                self._unreachable = True
                raise DBError(
                    "Supabase unreachable — project may be paused. "
                    "Visit https://supabase.com/dashboard to unpause it."
                ) from exc
            raise DBError(str(exc)) from exc

    async def update(self, table: str, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update row by id; return first updated row."""

        if not self._configured:
            raise DBError("Supabase is not configured — set SUPABASE_URL and SUPABASE_KEY in .env")
        if self._unreachable:
            raise DBError("Supabase is unreachable — project may be paused.")

        def _run() -> dict[str, Any]:
            response = self.client.table(table).update(data).eq("id", record_id).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
            return {}

        try:
            result = await asyncio.to_thread(_run)
            self._unreachable = False
            return result
        except DBError:
            raise
        except Exception as exc:
            if _is_connection_error(exc):
                self._unreachable = True
                raise DBError("Supabase unreachable — project may be paused.") from exc
            raise DBError(str(exc)) from exc

    async def select(
        self,
        table: str,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Select rows with optional equality filters.

        Returns an empty list on network/connection errors so the dashboard
        can still render instead of returning HTTP 500.
        """

        filters = filters or {}

        if not self._configured or self._unreachable:
            return []

        def _run() -> list[dict[str, Any]]:
            query = self.client.table(table).select("*").range(offset, offset + max(limit - 1, 0))
            for key, value in filters.items():
                query = query.eq(key, value)
            response = query.execute()
            return response.data or []

        try:
            result = await asyncio.to_thread(_run)
            self._unreachable = False  # reset on success
            return result
        except Exception as exc:
            if _is_connection_error(exc):
                if not self._unreachable:
                    logger.warning(
                        "Supabase unreachable ({}). "
                        "Check that your project is not paused at https://supabase.com/dashboard "
                        "and that SUPABASE_URL / SUPABASE_KEY are correct in .env. "
                        "Returning empty data until connection is restored.",
                        exc,
                    )
                self._unreachable = True
                return []
            raise DBError(str(exc)) from exc

    async def select_one(
        self, table: str, filters: Optional[dict[str, Any]] = None
    ) -> Optional[dict[str, Any]]:
        """Return first matching row or None."""

        rows = await self.select(table, filters, limit=1, offset=0)
        return rows[0] if rows else None

    async def count(self, table: str, filters: Optional[dict[str, Any]] = None) -> int:
        """Exact count with optional filters.

        Returns 0 on network/connection errors.
        """

        filters = filters or {}

        if not self._configured or self._unreachable:
            return 0

        def _run() -> int:
            query = self.client.table(table).select("id", count="exact")
            for key, value in filters.items():
                query = query.eq(key, value)
            result = query.execute()
            return int(result.count or 0)

        try:
            result = await asyncio.to_thread(_run)
            self._unreachable = False
            return result
        except Exception as exc:
            if _is_connection_error(exc):
                self._unreachable = True
                return 0
            raise DBError(str(exc)) from exc

    async def delete_agent_runs_older_than_days(self, days: int = 30) -> None:
        """Remove agent_runs rows older than the given number of days."""

        if not self._configured:
            return

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        def _run() -> None:
            self.client.table("agent_runs").delete().lt("started_at", cutoff).execute()

        try:
            await asyncio.to_thread(_run)
        except Exception as exc:
            logger.warning("delete_agent_runs_older_than_days failed: {}", exc)


_db_client: Optional[DBClient] = None


def get_db_client() -> DBClient:
    """Lazy singleton for database access."""

    global _db_client
    if _db_client is None:
        _db_client = DBClient()
    return _db_client
