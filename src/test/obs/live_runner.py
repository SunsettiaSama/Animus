from __future__ import annotations

import time
import uuid

from test.benchmark.metrics import CallMetrics, MetricsCollector, ScenarioResult, ToolMetrics
from test.benchmark.scenarios.base import Scenario
from test.obs.collector import get_collector


class LiveScenarioRunner:
    """Runs a Scenario against a real TaoLoop and returns a ScenarioResult.

    Unlike ScenarioRunner, this uses the actual LLM API rather than MockLLM.
    Obs events emitted by the instrumented llm.py/tao.py are collected for
    the duration of the run and aggregated into the returned ScenarioResult.

    post_process() is intentionally skipped so the run does not commit memory
    or modify the conversation context of the shared TaoLoop.
    """

    def __init__(self, scenario: Scenario, tao: object) -> None:
        self._scenario = scenario
        self._tao = tao

    def run(self) -> tuple[ScenarioResult, str | None]:
        from agent.react.tao import FinishEvent, MaxStepsEvent

        s = self._scenario
        session_id = str(uuid.uuid4())
        get_collector().set_session(session_id)

        final_answer: str | None = None
        t0 = time.perf_counter()

        for event in self._tao.stream(s.prompt):  # type: ignore[union-attr]
            if isinstance(event, FinishEvent):
                final_answer = event.answer
                break
            if isinstance(event, MaxStepsEvent):
                break

        wall_ms = (time.perf_counter() - t0) * 1000

        # Discard the pending finish state without committing to memory.
        self._tao.rollback_turn()  # type: ignore[union-attr]

        events = get_collector().read_session(session_id)

        llm_calls: list[CallMetrics] = []
        tool_calls: list[ToolMetrics] = []
        total_steps = 0
        retries = 0

        for ev in events:
            kind = ev.get("kind")
            if kind == "LLMCallEvent":
                llm_calls.append(CallMetrics(
                    call_id=ev.get("session_id", "")[:8],
                    prompt_tokens=ev.get("prompt_tokens", 0),
                    completion_tokens=ev.get("completion_tokens", 0),
                    latency_ms=ev.get("latency_ms", 0.0),
                    ttfb_ms=ev.get("ttfb_ms", 0.0),
                ))
            elif kind == "ToolCallEvent":
                step_idx = ev.get("step_index", 0)
                if step_idx + 1 > total_steps:
                    total_steps = step_idx + 1
                tool_calls.append(ToolMetrics(
                    tool_name=ev.get("tool_name", ""),
                    input_size=len(ev.get("input_summary", "")),
                    output_size=len(ev.get("output_summary", "")),
                    latency_ms=ev.get("latency_ms", 0.0),
                    success=True,
                ))
            elif kind == "ParseEvent" and ev.get("event_type") in ("retry_l2", "repair_l3"):
                retries += 1
            elif kind == "SessionEvent" and ev.get("event_type") == "finish":
                total_steps = ev.get("total_steps", total_steps)

        status = "done" if final_answer is not None else "failed"
        failure_cause = "none" if final_answer is not None else "max_steps"
        quality = _evaluate_quality(s, final_answer, tool_calls)

        result = ScenarioResult(
            scenario=s.name,
            status=status,
            failure_cause=failure_cause,
            wall_ms=wall_ms,
            steps=total_steps,
            llm_retries=retries,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            quality_score=quality,
            total_prompt_tokens=sum(c.prompt_tokens for c in llm_calls),
            total_completion_tokens=sum(c.completion_tokens for c in llm_calls),
        )
        return result, final_answer


def _evaluate_quality(
    scenario: Scenario,
    final_answer: str | None,
    tool_calls: list[ToolMetrics],
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
        if not tool_calls:
            passed += 1

    if "tool_calls_required" in exp:
        called = {tc.tool_name for tc in tool_calls}
        for tool in exp["tool_calls_required"]:
            checks += 1
            if tool in called:
                passed += 1

    return passed / checks if checks > 0 else None
