from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Scenario:
    name: str
    description: str
    prompt: str
    llm_script: list[str]
    tool_script: dict[str, list[str]]
    expected: dict
    thresholds: dict
    delay_ms: float = 0.0
    ttfb_ms: float = 0.0
    encoding: str = "cl100k_base"


class ScenarioLoader:
    @staticmethod
    def load(path: Path | str) -> Scenario:
        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return Scenario(
            name=data["name"],
            description=data.get("description", ""),
            prompt=data["prompt"],
            llm_script=data.get("llm_script", []),
            tool_script=data.get("tool_script") or {},
            expected=data.get("expected") or {},
            thresholds=data.get("thresholds") or {},
            delay_ms=float(data.get("delay_ms", 0.0)),
            ttfb_ms=float(data.get("ttfb_ms", 0.0)),
            encoding=data.get("encoding", "cl100k_base"),
        )

    @staticmethod
    def load_all(directory: Path | str) -> list[Scenario]:
        directory = Path(directory)
        return [
            ScenarioLoader.load(p)
            for p in sorted(directory.glob("*.yaml"))
        ]


def assert_scenario(result: "ScenarioResult", scenario: Scenario) -> None:  # type: ignore[name-defined]
    """Assert hard thresholds from the scenario YAML. Raises AssertionError on violation."""
    from test.benchmark.metrics import ScenarioResult  # local import avoids circular dep

    assert isinstance(result, ScenarioResult)
    t = scenario.thresholds
    total_tokens = result.total_prompt_tokens + result.total_completion_tokens

    if "max_total_tokens" in t:
        limit = int(t["max_total_tokens"])
        assert total_tokens <= limit, (
            f"[{scenario.name}] token usage {total_tokens} exceeds threshold {limit}"
        )

    if "max_wall_ms" in t:
        limit = float(t["max_wall_ms"])
        assert result.wall_ms <= limit, (
            f"[{scenario.name}] wall time {result.wall_ms:.0f} ms exceeds threshold {limit:.0f} ms"
        )

    assert result.status == "done", (
        f"[{scenario.name}] scenario did not finish: "
        f"status={result.status!r}, cause={result.failure_cause!r}"
    )


def compute_quality(result: "ScenarioResult", scenario: Scenario) -> float | None:  # type: ignore[name-defined]
    """Return a 0.0–1.0 quality score based on the 'expected' block, or None if no checks."""
    exp = scenario.expected
    if not exp:
        return None

    checks = 0
    passed = 0

    if "final_output_contains" in exp:
        patterns = exp["final_output_contains"]
        if isinstance(patterns, str):
            patterns = [patterns]
        final_ans = result.error or ""
        for call in result.llm_calls:
            _ = call  # answer is tracked via collector.mark_done
        # Retrieve from tool_calls not possible here; answer is in ScenarioResult.error field
        # The runner passes the final answer separately; quality check needs it injected.
        # We fall through; runner calls compute_quality with extra context via wrapper.
        checks += 1
        # Without the answer string we conservatively skip this check.
        # The runner uses _compute_quality_with_answer() instead.

    if "tool_calls_allowed" in exp and not exp["tool_calls_allowed"]:
        checks += 1
        if not result.tool_calls:
            passed += 1

    if "tool_calls_required" in exp:
        called_tools = {tc.tool_name for tc in result.tool_calls}
        for tool in exp["tool_calls_required"]:
            checks += 1
            if tool in called_tools:
                passed += 1

    if "max_steps" in exp:
        checks += 1
        if result.steps <= int(exp["max_steps"]):
            passed += 1

    if "max_wall_ms" in exp:
        checks += 1
        if result.wall_ms <= float(exp["max_wall_ms"]):
            passed += 1

    return passed / checks if checks > 0 else None


def compute_quality_with_answer(
    result: "ScenarioResult",  # type: ignore[name-defined]
    scenario: Scenario,
    final_answer: str | None,
) -> float | None:
    """Full quality score including final_output_contains check."""
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
        if not result.tool_calls:
            passed += 1

    if "tool_calls_required" in exp:
        called_tools = {tc.tool_name for tc in result.tool_calls}
        for tool in exp["tool_calls_required"]:
            checks += 1
            if tool in called_tools:
                passed += 1

    if "max_steps" in exp:
        checks += 1
        if result.steps <= int(exp["max_steps"]):
            passed += 1

    if "max_wall_ms" in exp:
        checks += 1
        if result.wall_ms <= float(exp["max_wall_ms"]):
            passed += 1

    return passed / checks if checks > 0 else None
