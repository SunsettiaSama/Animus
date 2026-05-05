from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from test.benchmark.metrics import (
    MetricsCollector,
    MetricsLLM,
    MockToolExecutor,
    ScenarioResult,
)
from test.benchmark.mock_llm import MockLLM
from test.benchmark.scenarios.base import Scenario

if TYPE_CHECKING:
    pass


@dataclass
class _ParsedStep:
    kind: str        # "finish" | "tool"
    thought: str
    action: str
    action_input: dict
    answer: str


def _parse_entry(text: str) -> _ParsedStep:
    """Minimal parser for scripted LLM responses in benchmark scenarios."""
    thought_m = re.search(
        r"Thought\s*[:：]\s*(.+?)(?=\n\s*(?:Action|Final Answer)\s*[:：]|$)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    thought = thought_m.group(1).strip() if thought_m else ""

    fa_m = re.search(r"Final Answer\s*[:：]\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    if fa_m:
        return _ParsedStep("finish", thought, "finish", {}, fa_m.group(1).strip())

    action_m = re.search(r"(?:^|\n)\s*Action\s*[:：]\s*(\S+)", text, re.IGNORECASE)
    input_m = re.search(
        r"Action Input\s*[:：]\s*(\{.*?\})", text, re.DOTALL | re.IGNORECASE
    )
    if action_m:
        action = action_m.group(1).strip()
        action_input: dict = {}
        if input_m:
            action_input = json.loads(input_m.group(1))
        return _ParsedStep("tool", thought, action, action_input, "")

    return _ParsedStep("finish", thought, "finish", {}, text.strip())


class ScenarioRunner:
    """
    Drives a Scenario through MockLLM + MockToolExecutor without requiring
    a real TaoLoop instance.  Collects token, latency and success metrics
    via MetricsCollector.
    """

    def __init__(self, scenario: Scenario, encoding: str | None = None) -> None:
        self._scenario = scenario
        self._encoding = encoding or scenario.encoding

    def run(self) -> tuple[ScenarioResult, str | None]:
        """Execute the scenario and return (ScenarioResult, final_answer | None)."""
        s = self._scenario
        collector = MetricsCollector(s.name)
        mock_llm = MockLLM(s.llm_script, delay_ms=s.delay_ms, ttfb_ms=s.ttfb_ms)
        metrics_llm = MetricsLLM(mock_llm, collector, encoding=self._encoding)
        tool_exec = MockToolExecutor(s.tool_script, collector)

        final_answer: str | None = None
        dummy_messages = [_DummyMessage(s.prompt)]

        for i, script_entry in enumerate(s.llm_script):
            raw = "".join(metrics_llm.stream_generate_messages(dummy_messages))
            step = _parse_entry(raw)
            collector.mark_step(i)

            if step.kind == "finish":
                collector.mark_done(step.answer)
                final_answer = step.answer
                break

            tool_exec.run(step.action, step.action_input)
        else:
            collector.mark_failed("max_steps")

        quality = _compute_quality_inline(collector, s, final_answer)
        result = collector.finalize(quality_score=quality)
        return result, final_answer


def _compute_quality_inline(
    collector: MetricsCollector,
    scenario: Scenario,
    final_answer: str | None,
) -> float | None:
    exp = scenario.expected
    if not exp:
        return None

    checks = 0
    passed = 0

    if "final_output_contains" in exp and final_answer is not None:
        patterns = exp["final_output_contains"]
        if isinstance(patterns, str):
            patterns = [patterns]
        checks += 1
        if any(p in final_answer for p in patterns):
            passed += 1

    if "tool_calls_allowed" in exp and not exp["tool_calls_allowed"]:
        checks += 1
        if not collector._tool_calls:
            passed += 1

    if "tool_calls_required" in exp:
        called = {tc.tool_name for tc in collector._tool_calls}
        for tool in exp["tool_calls_required"]:
            checks += 1
            if tool in called:
                passed += 1

    if "max_steps" in exp:
        checks += 1
        if collector._steps <= int(exp["max_steps"]):
            passed += 1

    return passed / checks if checks > 0 else None


class _DummyMessage:
    """Minimal message object; MockLLM ignores content but MetricsLLM reads .content."""

    def __init__(self, content: str) -> None:
        self.content = content
