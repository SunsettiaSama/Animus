from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseTTSProvider(ABC):
    @abstractmethod
    async def stream(self, text: str) -> AsyncIterator[bytes]:
        ...

    async def synthesize(self, text: str) -> bytes:
        chunks: list[bytes] = []
        async for chunk in self.stream(text):
            chunks.append(chunk)
        return b"".join(chunks)
