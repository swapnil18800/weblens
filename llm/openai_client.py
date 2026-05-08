"""
OpenAI fallback — gpt-4.1-mini (cost-efficient, strong quality).
Used when DeepSeek is unavailable or LLM_PROVIDER=openai.
"""
import logging
from typing import AsyncIterator
from openai import AsyncOpenAI
from config import settings
from .base import BaseLLMClient

logger = logging.getLogger(__name__)

_MODEL = "gpt-4.1-mini"


class OpenAIClient(BaseLLMClient):
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def astream(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        stream = await self._client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    async def acomplete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = await self._client.chat.completions.create(
            model=_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            stream=False,
        )
        return resp.choices[0].message.content or ""


def get_llm():
    """Return the best available LLM based on LLM_PROVIDER env var."""
    from llm.deepseek import DeepSeekClient

    provider = settings.llm_provider.lower()

    if provider == "openai" or not settings.deepseek_api_key:
        logger.info("[llm] Using OpenAI (%s)", _MODEL)
        return OpenAIClient()

    logger.info("[llm] Using DeepSeek V3 (deepseek-chat)")
    return DeepSeekClient()
