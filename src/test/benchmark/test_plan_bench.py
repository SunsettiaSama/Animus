"""
Plan orchestrator benchmark tests (mock LLM, no network).

Scenario:
  - plan_exec : agent issues a run_plan tool call, plan mock returns completion,
                agent then delivers a Final Answer.

Verifies that plan-related scenarios produce correct metrics (tool call recorded,
token budget respected, quality_score satisfies expected checks).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"

from test.benchmark.runner import ScenarioRunner
from test.benchmark.scenarios.base import ScenarioLoader, assert_scenario


def test_plan_exec_scenario(benchmark_results: list, benchmark_encoding: str) -> None:
    scenario = ScenarioLoader.load(SCENARIOS_DIR / "plan_exec.yaml")
    runner = ScenarioRunner(scenario, encoding=benchmark_encoding)
    result, final_answer = runner.run()
    benchmark_results.append(result)
    assert_scenario(result, scenario)
    assert final_answer is not None


def test_plan_exec_tool_recorded(benchmark_encoding: str) -> None:
    scenario = ScenarioLoader.load(SCENARIOS_DIR / "plan_exec.yaml")
    runner = ScenarioRunner(scenario, encoding=benchmark_encoding)
    result, _ = runner.run()

    tool_names = [tc.tool_name for tc in result.tool_calls]
    assert "run_plan" in tool_names, "run_plan tool must be recorded"

    plan_call = next(tc for tc in result.tool_calls if tc.tool_name == "run_plan")
    assert plan_call.success
    assert plan_call.output_size > 0


def test_plan_exec_multi_step_token_budget(benchmark_encoding: str) -> None:
    scenario = ScenarioLoader.load(SCENARIOS_DIR / "plan_exec.yaml")
    runner = ScenarioRunner(scenario, encoding=benchmark_encoding)
    result, _ = runner.run()

    assert len(result.llm_calls) == 2, "plan_exec has exactly two LLM calls"
    total = result.total_prompt_tokens + result.total_completion_tokens
    assert total > 0

    limit = scenario.thresholds.get("max_total_tokens", 9999)
    assert total <= limit, (
        f"token usage {total} exceeds threshold {limit}"
    )


def test_plan_exec_quality_score(benchmark_encoding: str) -> None:
    scenario = ScenarioLoader.load(SCENARIOS_DIR / "plan_exec.yaml")
    runner = ScenarioRunner(scenario, encoding=benchmark_encoding)
    result, _ = runner.run()

    assert result.quality_score is not None
    assert result.quality_score > 0.5, (
        f"plan_exec quality_score too low: {result.quality_score:.2f}"
    )
