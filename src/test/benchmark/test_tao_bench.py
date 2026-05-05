"""
TaoLoop benchmark tests (mock LLM, no network, no GPU).

Scenarios:
  - simple_qa   : single-turn Q&A, no tool calls
  - tool_web_search : one web_search call then a final answer

Metrics collected per scenario:
  prompt_tokens, completion_tokens, wall_ms, steps, quality_score
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


_SCENARIO_FILES = [
    SCENARIOS_DIR / "simple_qa.yaml",
    SCENARIOS_DIR / "tool_use.yaml",
]


@pytest.mark.parametrize("yaml_path", _SCENARIO_FILES, ids=lambda p: p.stem)
def test_scenario(yaml_path: Path, benchmark_results: list, benchmark_encoding: str) -> None:
    scenario = ScenarioLoader.load(yaml_path)
    runner = ScenarioRunner(scenario, encoding=benchmark_encoding)
    result, _ = runner.run()
    benchmark_results.append(result)
    assert_scenario(result, scenario)


def test_simple_qa_token_budget(benchmark_encoding: str) -> None:
    scenario = ScenarioLoader.load(SCENARIOS_DIR / "simple_qa.yaml")
    runner = ScenarioRunner(scenario, encoding=benchmark_encoding)
    result, final_answer = runner.run()

    assert result.status == "done"
    assert final_answer is not None
    total = result.total_prompt_tokens + result.total_completion_tokens
    assert total > 0, "Token counting must produce a non-zero result"
    assert result.llm_calls, "At least one LLM call must be recorded"
    assert result.llm_calls[0].ttfb_ms >= 0


def test_tool_use_records_tool_metrics(benchmark_encoding: str) -> None:
    scenario = ScenarioLoader.load(SCENARIOS_DIR / "tool_use.yaml")
    runner = ScenarioRunner(scenario, encoding=benchmark_encoding)
    result, _ = runner.run()

    assert result.status == "done"
    assert result.tool_calls, "Tool call must be recorded"
    tc = result.tool_calls[0]
    assert tc.tool_name == "web_search"
    assert tc.input_size > 0
    assert tc.output_size > 0
    assert tc.latency_ms >= 0
    assert tc.success


def test_quality_score_simple_qa(benchmark_encoding: str) -> None:
    scenario = ScenarioLoader.load(SCENARIOS_DIR / "simple_qa.yaml")
    runner = ScenarioRunner(scenario, encoding=benchmark_encoding)
    result, _ = runner.run()

    assert result.quality_score is not None
    assert result.quality_score > 0.0, "simple_qa should pass all expected checks"


def test_retry_counting(benchmark_encoding: str) -> None:
    from test.benchmark.metrics import MetricsCollector

    collector = MetricsCollector("retry_test")
    assert collector._retries == 0
    collector.mark_retry()
    collector.mark_retry()
    assert collector._retries == 2
    collector.mark_done("ok")
    r = collector.finalize()
    assert r.llm_retries == 2
    assert r.status == "done"
