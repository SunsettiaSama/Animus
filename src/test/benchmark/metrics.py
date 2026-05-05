from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Generator, Protocol, runtime_checkable


@dataclass
class CallMetrics:
    call_id: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    ttfb_ms: float
    success: bool = True


@dataclass
class ToolMetrics:
    tool_name: str
    input_size: int
    output_size: int
    latency_ms: float
    success: bool


@dataclass
class ScenarioResult:
    scenario: str
    status: str                        # done | failed | aborted
    failure_cause: str                 # parse_error | tool_error | max_steps | timeout | none
    wall_ms: float
    steps: int
    llm_retries: int
    llm_calls: list[CallMetrics]
    tool_calls: list[ToolMetrics]
    quality_score: float | None
    total_prompt_tokens: int
    total_completion_tokens: int
    error: str | None = None


class MetricsCollector:
    def __init__(self, scenario_name: str) -> None:
        self._name = scenario_name
        self._t0 = time.perf_counter()
        self._llm_calls: list[CallMetrics] = []
        self._tool_calls: list[ToolMetrics] = []
        self._steps = 0
        self._retries = 0
        self._status = "failed"
        self._failure_cause = "max_steps"
        self._error: str | None = None

    def record_llm_call(
        self,
        *,
        call_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        ttfb_ms: float = 0.0,
        success: bool = True,
    ) -> None:
        self._llm_calls.append(
            CallMetrics(call_id, prompt_tokens, completion_tokens, latency_ms, ttfb_ms, success)
        )

    def record_tool_call(
        self,
        *,
        tool_name: str,
        input_size: int,
        output_size: int,
        latency_ms: float,
        success: bool = True,
    ) -> None:
        self._tool_calls.append(
            ToolMetrics(tool_name, input_size, output_size, latency_ms, success)
        )

    def mark_step(self, idx: int) -> None:
        self._steps = idx + 1

    def mark_retry(self) -> None:
        self._retries += 1

    def mark_done(self, answer: str) -> None:  # noqa: ARG002
        self._status = "done"
        self._failure_cause = "none"

    def mark_failed(self, cause: str, error: str | None = None) -> None:
        self._status = "failed"
        self._failure_cause = cause
        self._error = error

    def finalize(self, quality_score: float | None = None) -> ScenarioResult:
        wall_ms = (time.perf_counter() - self._t0) * 1000
        total_prompt = sum(c.prompt_tokens for c in self._llm_calls)
        total_completion = sum(c.completion_tokens for c in self._llm_calls)
        return ScenarioResult(
            scenario=self._name,
            status=self._status,
            failure_cause=self._failure_cause,
            wall_ms=wall_ms,
            steps=self._steps,
            llm_retries=self._retries,
            llm_calls=self._llm_calls,
            tool_calls=self._tool_calls,
            quality_score=quality_score,
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            error=self._error,
        )


@runtime_checkable
class LLMProtocol(Protocol):
    def stream_generate_messages(self, messages: list) -> Generator[str, None, None]: ...
    def generate_messages(self, messages: list) -> str: ...
    def generate(self, prompt: str) -> str: ...
    def stream_generate(self, prompt: str) -> Generator[str, None, None]: ...


class MetricsLLM:
    """Transparent wrapper around any LLM-like object that records call metrics."""

    def __init__(
        self,
        inner: LLMProtocol,
        collector: MetricsCollector,
        encoding: str = "cl100k_base",
    ) -> None:
        from test.benchmark.tokenizer import count_tokens as _count_tokens
        self._inner = inner
        self._collector = collector
        self._encoding = encoding
        self._count_tokens = _count_tokens

    def _count(self, text: str) -> int:
        return self._count_tokens(text, self._encoding)

    def _prompt_tokens(self, messages: list) -> int:
        return sum(self._count(getattr(m, "content", str(m))) for m in messages)

    def stream_generate_messages(self, messages: list) -> Generator[str, None, None]:
        prompt_tokens = self._prompt_tokens(messages)
        call_id = uuid.uuid4().hex[:8]
        t0 = time.perf_counter()
        first = True
        ttfb = 0.0
        chunks: list[str] = []

        for chunk in self._inner.stream_generate_messages(messages):
            if first:
                ttfb = (time.perf_counter() - t0) * 1000
                first = False
            chunks.append(chunk)
            yield chunk

        latency = (time.perf_counter() - t0) * 1000
        completion_tokens = self._count("".join(chunks))
        self._collector.record_llm_call(
            call_id=call_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency,
            ttfb_ms=ttfb,
        )

    def generate_messages(self, messages: list) -> str:
        prompt_tokens = self._prompt_tokens(messages)
        call_id = uuid.uuid4().hex[:8]
        t0 = time.perf_counter()
        output = self._inner.generate_messages(messages)
        latency = (time.perf_counter() - t0) * 1000
        self._collector.record_llm_call(
            call_id=call_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=self._count(output),
            latency_ms=latency,
            ttfb_ms=latency,
        )
        return output

    def generate(self, prompt: str) -> str:
        return self.generate_messages([type("_M", (), {"content": prompt})()])

    def stream_generate(self, prompt: str) -> Generator[str, None, None]:
        yield from self.stream_generate_messages([type("_M", (), {"content": prompt})()])


class MockToolExecutor:
    """Scripted tool executor that does not depend on ActionExecutor."""

    def __init__(
        self,
        tool_script: dict[str, list[str]],
        collector: MetricsCollector,
    ) -> None:
        self._script = {k: list(v) for k, v in tool_script.items()}
        self._idx: dict[str, int] = {}
        self._collector = collector

    def run(self, tool_name: str, args: dict) -> str:
        input_size = len(str(args))
        t0 = time.perf_counter()

        if tool_name in self._script:
            script = self._script[tool_name]
            idx = self._idx.get(tool_name, 0)
            output = script[min(idx, len(script) - 1)]
            self._idx[tool_name] = idx + 1
            success = True
        else:
            output = f"[mock] unknown tool: {tool_name!r}"
            success = False

        latency_ms = (time.perf_counter() - t0) * 1000
        self._collector.record_tool_call(
            tool_name=tool_name,
            input_size=input_size,
            output_size=len(output),
            latency_ms=latency_ms,
            success=success,
        )
        return output
