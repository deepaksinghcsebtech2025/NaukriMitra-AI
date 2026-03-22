"""OpenRouter client unit tests with mocks."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.llm import OpenRouterClient


def test_chat_returns_non_empty_string():
    async def _run() -> None:
        client = OpenRouterClient()
        fake_resp = MagicMock()
        fake_resp.choices = [MagicMock(message=MagicMock(content="hello from model"))]

        with patch.object(client.client.chat.completions, "create", new_callable=AsyncMock) as m:
            m.return_value = fake_resp
            out = await client.chat([{"role": "user", "content": "hi"}])
        assert isinstance(out, str)
        assert len(out) > 0

    asyncio.run(_run())


def test_extract_json_returns_dict():
    async def _run() -> None:
        client = OpenRouterClient()
        fake_resp = MagicMock()
        fake_resp.choices = [MagicMock(message=MagicMock(content='{"a": 1}'))]

        with patch.object(client.client.chat.completions, "create", new_callable=AsyncMock) as m:
            m.return_value = fake_resp
            with patch("core.llm.get_cache_client") as gc:
                cache = MagicMock()
                cache.get = AsyncMock(return_value=None)
                cache.set = AsyncMock(return_value=True)
                gc.return_value = cache
                data = await client.extract_json("ping", use_cache=False)
        assert data == {"a": 1}

    asyncio.run(_run())


def test_fallback_when_primary_fails():
    async def _run() -> None:
        client = OpenRouterClient()
        ok = MagicMock()
        ok.choices = [MagicMock(message=MagicMock(content="fallback-ok"))]

        async def side_effect(*args, **kwargs):
            model = kwargs.get("model", "")
            if model == client.settings.llm_primary:
                raise RuntimeError("bad primary")
            return ok

        with patch.object(client.client.chat.completions, "create", new_callable=AsyncMock) as m:
            m.side_effect = side_effect
            out = await client.chat(
                [{"role": "user", "content": "x"}],
                model=client.settings.llm_primary,
            )
        assert out == "fallback-ok"

    asyncio.run(_run())
