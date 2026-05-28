from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from test.benchmark.metrics import (
    MetricsCollector,
    MetricsLLM,
    MockToolExecutor,
    ScenarioResult,
)
from test.benchmark.mock_llm import MockLLM
from test.benchmark.scenarios.base import Scenario, ScenarioLoader, compute_quality_with_answer

if TYPE_CHECKING:
    pass


@dataclass
class _ParsedStep:
    kind: str        # "finish" | "tool"
    thought: str
    action: str
    action_input: dict
    answer: str


_MINI_FINISH_ACTIONS = frozenset({
    "finish", "final_answer", "finalanswer", "done",
})


def _parse_entry(text: str) -> _ParsedStep:
    """Minimal parser for scripted LLM responses in benchmark scenarios.

    Recognises both legacy ``Final Answer: <text>`` format and the canonical
    ReAct ``Action: finish / Action Input: {"answer": "..."}`` format so that
    all YAML scenarios are handled regardless of which convention they use.
    """
    thought_m = re.search(
        r"Thought\s*[:：]\s*(.+?)(?=\n\s*(?:Action|Final Answer)\s*[:：]|$)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    thought = thought_m.group(1).strip() if thought_m else ""

    # Legacy: "Final Answer: <text>"
    fa_m = re.search(r"Final Answer\s*[:：]\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    if fa_m:
        return _ParsedStep("finish", thought, "finish", {}, fa_m.group(1).strip())

    action_m = re.search(r"(?:^|\n)\s*Action\s*[:：]\s*(\S+)", text, re.IGNORECASE)
    input_m = re.search(
        r"Action Input\s*[:：]\s*(\{.*?\})", text, re.DOTALL | re.IGNORECASE
    )

    if action_m:
        action = action_m.group(1).strip().lower()

        # Canonical: "Action: finish / Action Input: {"answer": "..."}"
        if action in _MINI_FINISH_ACTIONS:
            answer = ""
            if input_m:
                parsed = json.loads(input_m.group(1))
                answer = parsed.get("answer", "")
            if not answer and thought:
                answer = thought
            return _ParsedStep("finish", thought, "finish", {}, answer)

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

        partial = collector.finalize()
        quality = compute_quality_with_answer(partial, s, final_answer)
        result = collector.finalize(quality_score=quality)
        return result, final_answer


class _DummyMessage:
    """Minimal message object; MockLLM ignores content but MetricsLLM reads .content."""

    def __init__(self, content: str) -> None:
        self.content = content


# ── ScenarioFileRunner �?BenchmarkRunner implementation ───────────────────────


class ScenarioFileRunner:
    """
    BenchmarkRunner that discovers and runs all YAML scenarios in a directory.

    This is the smoke-gate runner: it uses the lightweight ScenarioRunner
    (with its own mini-parser) for maximum speed, making it suitable for
    every-PR CI runs where zero network / zero GPU is required.

    To add a new YAML-driven scenario to the smoke suite, simply drop a
    .yaml file in the scenarios directory �?no code changes needed.
    """

    name = "scenario_file"
    gate = "smoke"

    def __init__(self, scenarios_dir: Path) -> None:
        self._dir = scenarios_dir

    def run_all(self) -> list[ScenarioResult]:
        results: list[ScenarioResult] = []
        for yaml_path in sorted(self._dir.glob("*.yaml")):
            scenario = ScenarioLoader.load(yaml_path)
            result, _ = ScenarioRunner(scenario).run()
            results.append(result)
        return results

    def describe(self) -> str:
        yamls = sorted(self._dir.glob("*.yaml"))
        return f"{len(yamls)} YAML scenario(s) in {self._dir.name}/"
