from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseLLMClient(ABC):
    @abstractmethod
    async def astream(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Yield response tokens one at a time."""
        ...

    @abstractmethod
    async def acomplete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
    ) -> str:
        """Return full response text (non-streaming)."""
        ...
