from __future__ import annotations

from abc import ABC, abstractmethod


class BaseSTTProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes, mime_type: str = "audio/webm") -> str:
        ...
