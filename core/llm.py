"""OpenRouter client via OpenAI-compatible async API."""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from core.cache import get_cache_client
from core.config import get_settings
from core.exceptions import LLMError
from core.logger import logger


class OpenRouterClient:
    """Chat and JSON extraction with primary/fallback models and optional Redis cache."""

    def __init__(self) -> None:
        """Configure AsyncOpenAI pointed at OpenRouter."""

        self.settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=self.settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/ultra-job-agent",
                "X-Title": "Ultra Job Agent",
            },
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    async def chat(self, messages: list, model: Optional[str] = None, max_tokens: int = 2000) -> str:
        """Complete chat; fall back to secondary model on failure."""

        api_key = (self.settings.openrouter_api_key or "").strip()
        if not api_key:
            raise LLMError(
                "OPENROUTER_API_KEY is not set. Add it to your .env (copy from .env.example). "
                "Free keys: https://openrouter.ai/"
            )

        primary = model or self.settings.llm_primary
        try:
            resp = await self.client.chat.completions.create(
                model=primary,
                messages=messages,
                max_tokens=max_tokens,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as primary_exc:
            logger.warning("Primary LLM failed ({}), trying fallback: {}", primary, primary_exc)
            resp = await self.client.chat.completions.create(
                model=self.settings.llm_fallback,
                messages=messages,
                max_tokens=max_tokens,
            )
            return (resp.choices[0].message.content or "").strip()

    async def extract_json(self, prompt: str, use_cache: bool = True) -> dict:
        """Ask for JSON only; parse, optionally cache 24h."""

        cache_key = "llm:" + hashlib.sha256(prompt.encode()).hexdigest()[:16]
        if use_cache:
            cached = await get_cache_client().get(cache_key)
            if cached:
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass

        messages = [
            {
                "role": "system",
                "content": "Respond ONLY with valid JSON. No markdown, no explanation, no code fences.",
            },
            {"role": "user", "content": prompt},
        ]
        raw = await self.chat(messages)
        raw = raw.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"JSON parse failed: {exc}\nRaw: {raw[:200]}") from exc

        if use_cache:
            await get_cache_client().set(cache_key, json.dumps(result), ttl_seconds=86400)

        return result


_llm_client: Optional[OpenRouterClient] = None


def get_llm_client() -> OpenRouterClient:
    """Singleton LLM client."""

    global _llm_client
    if _llm_client is None:
        _llm_client = OpenRouterClient()
    return _llm_client
