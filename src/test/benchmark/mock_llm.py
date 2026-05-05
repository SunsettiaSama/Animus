from __future__ import annotations

import time
from typing import Generator


class MockLLM:
    """
    Scripted LLM that returns pre-defined responses in sequence.

    Each call to stream_generate_messages / generate_messages consumes the
    next entry in ``script``.  When the list is exhausted the last entry is
    repeated indefinitely, so short scripts still produce a valid finish.
    """

    def __init__(
        self,
        script: list[str],
        delay_ms: float = 0.0,
        ttfb_ms: float = 0.0,
    ) -> None:
        self._script = script
        self._idx = 0
        self._delay_ms = delay_ms
        self._ttfb_ms = ttfb_ms

    def _next(self) -> str:
        resp = self._script[min(self._idx, len(self._script) - 1)]
        self._idx += 1
        return resp

    def reset(self) -> None:
        self._idx = 0

    # ── LLMProtocol interface ─────────────────────────────────────────────────

    def stream_generate_messages(self, messages: list) -> Generator[str, None, None]:  # noqa: ARG002
        if self._ttfb_ms:
            time.sleep(self._ttfb_ms / 1000)
        resp = self._next()
        if self._delay_ms:
            time.sleep(self._delay_ms / 1000)
        yield resp

    def generate_messages(self, messages: list) -> str:  # noqa: ARG002
        if self._delay_ms:
            time.sleep(self._delay_ms / 1000)
        return self._next()

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        return self.generate_messages([])

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:  # noqa: ARG002
        yield from self.stream_generate_messages([])
