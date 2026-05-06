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


# ── MockLLMAdapter ────────────────────────────────────────────────────────────


class MockLLMAdapter:
    """
    Wraps MockLLM to satisfy the BaseLLM interface required by TaoLoop.

    TaoLoop's constructor accepts LLM (a concrete facade over BaseLLM).  At
    runtime only the BaseLLM abstract interface is exercised, so passing a
    MockLLMAdapter works without importing the heavy provider dependencies.

    We do NOT inherit BaseLLM directly to avoid forcing llm_core imports at
    module load time (which would pull in transformers / openai even in CI).
    The adapter is duck-type compatible with BaseLLM.
    """

    def __init__(self, inner: MockLLM) -> None:
        self._inner = inner

    def generate(self, prompt: str) -> str:
        return self._inner.generate(prompt)

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        yield from self._inner.stream_generate(prompt)

    def generate_messages(self, messages: list) -> str:
        return self._inner.generate_messages(messages)

    def stream_generate_messages(self, messages: list) -> Generator[str, None, None]:
        yield from self._inner.stream_generate_messages(messages)


# ── MockSubAgentRunner ────────────────────────────────────────────────────────


class MockSubAgentRunner:
    """
    Scripted replacement for SubAgentRunner used in cluster benchmark tests.

    Each call to run_sync() matches the instruction text against ``script``
    (a list of ``{instruction_contains, answer}`` dicts) and returns the
    first matching scripted answer.  A call log is maintained for assertions.
    """

    def __init__(self, script: list[dict]) -> None:
        self._script = script
        self.call_log: list[dict] = []

    def run_sync(
        self,
        instruction: str,
        profile,
        llm_cfg_path: str,
        event_callback=None,  # noqa: ARG002
    ) -> dict:
        self.call_log.append({"instruction": instruction})
        for rule in self._script:
            if rule.get("instruction_contains", "") in instruction:
                answer = rule.get("answer", "[mock sub-agent]")
                return {
                    "answer": answer,
                    "step_count": 1,
                    "steps_log": [f"[mock delegate] {answer[:80]}"],
                }
        return {
            "answer": "[mock sub-agent: no matching script entry]",
            "step_count": 1,
            "steps_log": [],
        }
