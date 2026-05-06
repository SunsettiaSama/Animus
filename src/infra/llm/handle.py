from __future__ import annotations

from typing import Generator

from langchain_core.messages import BaseMessage

from infra.llm.llm import BaseLLM, LLM


class LLMHandle(BaseLLM):
    """Mutable wrapper around an LLM instance.

    Every TaoLoop sub-component that needs an LLM receives the **same**
    LLMHandle at construction time.  When the user changes model / API key
    and LLMService.start() creates a new LLM object, a single call to
    ``handle.update(new_llm)`` propagates the change to every component
    automatically — no per-component update chain required.

    LLMHandle implements BaseLLM so it satisfies every type annotation that
    expects a BaseLLM (or its concrete subclass LLM).
    """

    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def update(self, llm: LLM) -> None:
        self._llm = llm

    # ── BaseLLM interface (forwards to inner LLM) ─────────────────────────────

    def generate(self, prompt: str) -> str:
        return self._llm.generate(prompt)

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        yield from self._llm.stream_generate(prompt)

    def generate_messages(self, messages: list[BaseMessage]) -> str:
        return self._llm.generate_messages(messages)

    def stream_generate_messages(
        self, messages: list[BaseMessage]
    ) -> Generator[str, None, None]:
        yield from self._llm.stream_generate_messages(messages)
