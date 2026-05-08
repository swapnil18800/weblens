"""
DeepSeek V3 via OpenAI-compatible API.
Model: deepseek-chat (= DeepSeek V3) — no daily quota, excellent reasoning.
"""
import logging
from typing import AsyncIterator
from openai import AsyncOpenAI
from config import settings
from .base import BaseLLMClient

logger = logging.getLogger(__name__)

_MODEL = "deepseek-chat"
_BASE_URL = "https://api.deepseek.com"


class DeepSeekClient(BaseLLMClient):
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=_BASE_URL,
        )

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
