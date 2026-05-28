"""
ClusterRunner �?smoke-gate BenchmarkRunner for multi-agent cluster workflows.

Tests the full parent-agent �?delegate_task �?sub-agent �?answer pipeline
using a lightweight mini-loop (no real TaoLoop required, no torch dependency):

  * MockLLM feeds scripted parent-agent responses step by step.
  * A mini-parser recognises Action: delegate_task / Action: finish / tool calls.
  * DelegateTaskSkill.execute() is called directly with MockSubAgentRunner,
    exercising the real skill code (argument validation, event forwarding, etc.)
    without needing a live LLM or the full agent memory stack.
  * MockSubAgentRunner returns scripted answers keyed by instruction substring.

Scenario YAML format (place files in scenarios/cluster/):

    name: single_delegate
    prompt: "..."
    parent_llm_script:           # parent agent's scripted LLM turns
      - |
        Thought: ...
        Action: delegate_task
        Action Input: {"instruction": "...", "profile": "researcher"}
      - |
        Thought: ...
        Action: finish
        Action Input: {"answer": "final answer here"}
    parent_tool_script: {}       # optional extra scripted tools for parent
    sub_agent_script:
      - instruction_contains: "keyword"
        answer: "sub-agent answer for instructions that contain keyword"
    expected:
      final_output_contains: ["keyword"]
      sub_agents_called: 1       # exact number of delegate_task invocations
    thresholds:
      max_wall_ms: 10000
      max_steps: 10
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from test.benchmark.metrics import ScenarioResult

_SRC = Path(__file__).resolve().parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ── Scenario dataclass ────────────────────────────────────────────────────────


@dataclass
class ClusterScenario:
    name: str
    description: str
    prompt: str
    parent_llm_script: list[str]
    parent_tool_script: dict[str, list[str]]
    sub_agent_script: list[dict]
    expected: dict
    thresholds: dict
    delay_ms: float = 0.0


class ClusterScenarioLoader:
    @staticmethod
    def load(path: Path | str) -> ClusterScenario:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return ClusterScenario(
            name=data["name"],
            description=data.get("description", ""),
            prompt=data["prompt"],
            parent_llm_script=data.get("parent_llm_script", []),
            parent_tool_script=data.get("parent_tool_script") or {},
            sub_agent_script=data.get("sub_agent_script") or [],
            expected=data.get("expected") or {},
            thresholds=data.get("thresholds") or {},
            delay_ms=float(data.get("delay_ms", 0.0)),
        )

    @staticmethod
    def load_all(directory: Path | str) -> list[ClusterScenario]:
        directory = Path(directory)
        return [ClusterScenarioLoader.load(p) for p in sorted(directory.glob("*.yaml"))]


# ── Mini-parser ───────────────────────────────────────────────────────────────


@dataclass
class _Step:
    kind: str     # "finish" | "delegate" | "tool"
    thought: str
    action: str
    action_input: dict
    answer: str   # populated only when kind == "finish"


_FINISH_ACTIONS = frozenset({"finish", "final_answer", "finalanswer", "done"})


def _parse_step(text: str) -> _Step:
    thought_m = re.search(
        r"Thought\s*[:：]\s*(.+?)(?=\n\s*(?:Action|Final Answer)\s*[:：]|$)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    thought = thought_m.group(1).strip() if thought_m else ""

    fa_m = re.search(r"Final Answer\s*[:：]\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    if fa_m:
        return _Step("finish", thought, "finish", {}, fa_m.group(1).strip())

    action_m = re.search(r"(?:^|\n)\s*Action\s*[:：]\s*(\S+)", text, re.IGNORECASE)
    input_m = re.search(
        r"Action Input\s*[:：]\s*(\{.*?\})", text, re.DOTALL | re.IGNORECASE
    )

    action_input: dict = {}
    if input_m:
        action_input = json.loads(input_m.group(1))

    if action_m:
        action = action_m.group(1).strip().lower()

        if action in _FINISH_ACTIONS:
            answer = action_input.get("answer", "") or thought
            return _Step("finish", thought, "finish", action_input, answer)

        if action == "delegate_task":
            return _Step("delegate", thought, action, action_input, "")

        return _Step("tool", thought, action, action_input, "")

    return _Step("finish", thought, "finish", {}, text.strip())


# ── Core runner ───────────────────────────────────────────────────────────────


def _run_cluster_scenario(scenario: ClusterScenario) -> "ScenarioResult":
    from agent.profile import SubAgentConfig
    from agent.react.action.skill.delegate_task import DelegateTaskSkill

    from test.benchmark.metrics import MetricsCollector, MetricsLLM
    from test.benchmark.mock_llm import MockLLM, MockSubAgentRunner

    # Sub-agent runner wired to scripted answers.
    mock_runner = MockSubAgentRunner(scenario.sub_agent_script)

    # DelegateTaskSkill instance that uses MockSubAgentRunner.
    agent_cfg = SubAgentConfig(llm_cfg_path="mock.yaml")
    delegate_skill = DelegateTaskSkill(runner=mock_runner, cfg=agent_cfg)

    # Scripted tool executor for non-delegate tools.
    tool_script_idx: dict[str, int] = {}

    def _run_tool(name: str, args: dict) -> str:
        script = scenario.parent_tool_script.get(name)
        if script is None:
            return f"[mock] unknown tool: {name!r}"
        idx = tool_script_idx.get(name, 0)
        out = script[min(idx, len(script) - 1)]
        tool_script_idx[name] = idx + 1
        return out

    collector = MetricsCollector(scenario.name)
    mock_llm = MockLLM(scenario.parent_llm_script, delay_ms=scenario.delay_ms)

    class _Msg:
        def __init__(self, content: str) -> None:
            self.content = content

    metrics_llm = MetricsLLM(mock_llm, collector)
    dummy_messages = [_Msg(scenario.prompt)]

    final_answer: str | None = None
    sub_agents_called = 0
    max_steps = scenario.thresholds.get("max_steps", 15) if scenario.thresholds else 15

    for i in range(max_steps):
        raw = "".join(metrics_llm.stream_generate_messages(dummy_messages))
        step = _parse_step(raw)
        collector.mark_step(i)

        if step.kind == "finish":
            final_answer = step.answer
            collector.mark_done(final_answer)
            break

        if step.kind == "delegate":
            instruction = step.action_input.get("instruction", "")
            profile = step.action_input.get("profile", "minimal")
            sub_agents_called += 1
            delegate_skill.execute(instruction=instruction, profile=profile)

        else:
            _run_tool(step.action, step.action_input)
    else:
        collector.mark_failed("max_steps")

    quality = _compute_quality(collector, scenario, final_answer, sub_agents_called)
    return collector.finalize(quality_score=quality)


def _compute_quality(
    collector,
    scenario: ClusterScenario,
    final_answer: str | None,
    sub_agents_called: int,
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

    if "sub_agents_called" in exp:
        checks += 1
        if sub_agents_called == int(exp["sub_agents_called"]):
            passed += 1

    if "max_steps" in exp:
        checks += 1
        if collector._steps <= int(exp["max_steps"]):
            passed += 1

    return passed / checks if checks > 0 else None


# ── BenchmarkRunner implementation ────────────────────────────────────────────


class ClusterRunner:
    """
    BenchmarkRunner for multi-agent cluster workflow tests.

    Uses a lightweight mini-loop (no TaoLoop, no torch) to test the
    parent-agent �?DelegateTaskSkill �?MockSubAgentRunner delegation
    path end-to-end.  The real DelegateTaskSkill (including Pydantic
    arg validation and event forwarding) is exercised for every step.
    """

    name = "cluster"
    gate = "smoke"

    def __init__(self, scenarios_dir: Path) -> None:
        self._dir = scenarios_dir

    def run_all(self) -> "list[ScenarioResult]":
        results: list = []
        for yaml_path in sorted(self._dir.glob("*.yaml")):
            scenario = ClusterScenarioLoader.load(yaml_path)
            results.append(_run_cluster_scenario(scenario))
        return results

    def describe(self) -> str:
        yamls = sorted(self._dir.glob("*.yaml"))
        return (
            f"{len(yamls)} cluster scenario(s) via DelegateTaskSkill + "
            f"MockSubAgentRunner in {self._dir.name}/"
        )
