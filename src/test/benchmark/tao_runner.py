"""
TaoLoopRunner — regression-gate BenchmarkRunner that exercises the real
TaoLoop pipeline (parse_llm_output, L2/L3 repair chain, ActionExecutor).

Unlike ScenarioFileRunner (which uses its own mini-parser), this runner
injects MockLLM + ScriptActionExecutor into a real TaoLoop instance so
that every parse, retry and repair path is exercised under test conditions.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from test.benchmark.metrics import ScenarioResult
    from test.benchmark.scenarios.base import Scenario

_SRC = Path(__file__).resolve().parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _run_one(scenario: "Scenario") -> "ScenarioResult":
    """Drive a single Scenario through TaoLoop, collect events, return ScenarioResult."""
    from agent.react.tao import (
        FinishEvent,
        MaxStepsEvent,
        RetryEvent,
        StepEvent,
        TaoLoop,
    )
    from config.agent.memory.memory_config import MemoryConfig
    from config.agent.persona_config import PersonaConfig
    from config.agent.tao_config import TaoConfig
    from config.agent.trace_config import TraceConfig

    from test.benchmark.metrics import MetricsCollector
    from test.benchmark.mock_executor import ScriptActionExecutor
    from test.benchmark.mock_llm import MockLLM, MockLLMAdapter
    from test.benchmark.scenarios.base import compute_quality_with_answer

    # Minimal TaoConfig: all persistent memory and persona disabled so the
    # runner stays fast and deterministic (no disk I/O, no vector DB).
    memory = MemoryConfig()
    memory.long_term.enabled = False
    memory.milestone.enabled = False
    memory.medium_term.enabled = False

    cfg = TaoConfig(
        max_steps=scenario.thresholds.get("max_steps", 10) if scenario.thresholds else 10,
        memory=memory,
        persona=PersonaConfig(enabled=False),
        trace=TraceConfig(enabled=False),
        repair_llm=None,
    )

    inner_llm = MockLLM(scenario.llm_script, delay_ms=scenario.delay_ms, ttfb_ms=scenario.ttfb_ms)
    llm = MockLLMAdapter(inner_llm)
    executor = ScriptActionExecutor(scenario.tool_script)
    tool_descs = {name: f"[mock] {name}" for name in executor.available_actions}

    tao = TaoLoop(
        llm=llm,
        executor=executor,
        tool_descriptions=tool_descs,
        cfg=cfg,
    )

    collector = MetricsCollector(scenario.name)
    final_answer: str | None = None

    for event in tao.stream(scenario.prompt):
        if isinstance(event, StepEvent):
            collector.mark_step(event.index)
        elif isinstance(event, RetryEvent):
            collector.mark_retry()
        elif isinstance(event, FinishEvent):
            final_answer = event.answer
            collector.mark_done(final_answer)
        elif isinstance(event, MaxStepsEvent):
            collector.mark_failed("max_steps")

    if final_answer is None and collector._status != "failed":
        collector.mark_failed("max_steps")

    partial = collector.finalize()
    quality = compute_quality_with_answer(partial, scenario, final_answer)
    return collector.finalize(quality_score=quality)


class TaoLoopRunner:
    """
    BenchmarkRunner implementation for regression-gate integration tests.

    Loads all YAML scenarios from *scenarios_dir* and runs each through a
    real TaoLoop instance (MockLLM + ScriptActionExecutor injected).

    This is the primary runner for verifying that parser fixes, repair
    chain changes, and tool dispatch logic behave correctly end-to-end.
    """

    name = "tao_loop"
    gate = "regression"

    def __init__(self, scenarios_dir: Path) -> None:
        # Probe import at construction time so that an ImportError or OSError
        # (e.g. torch DLL missing) surfaces immediately and is caught by the
        # registration guard in __main__.py rather than during run_all().
        import agent.react.tao  # noqa: F401
        self._dir = scenarios_dir

    def run_all(self) -> list[ScenarioResult]:
        from test.benchmark.scenarios.base import ScenarioLoader

        results: list[ScenarioResult] = []
        for yaml_path in sorted(self._dir.glob("*.yaml")):
            scenario = ScenarioLoader.load(yaml_path)
            results.append(_run_one(scenario))
        return results

    def describe(self) -> str:
        yamls = sorted(self._dir.glob("*.yaml"))
        return f"{len(yamls)} YAML scenario(s) via real TaoLoop in {self._dir.name}/"
