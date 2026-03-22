"""Shared pytest configuration."""

import pytest

from core.config import get_settings


@pytest.fixture(autouse=True)
def _test_openrouter_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM tests need a non-empty key; real HTTP is mocked."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-mocked-not-real")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
