"""Smoke test / offline unit test for agent.flow.coding."""
from __future__ import annotations

import asyncio
import json

import pytest

from agent.flow.coding import CodeOrchestrator, CodingConfig, CodeResult
from agent.flow.coding.planner import _extract_json, _nodes_to_manifests


# ── Mock LLM ──────────────────────────────────────────────────────────────────

_PLAN_JSON = json.dumps([
    {"task_id": "design_api", "role": "design",
     "description": "Design HTTP rate limiter API", "depends_on": []},
    {"task_id": "impl_limiter", "role": "implement",
     "description": "Implement the rate limiter", "depends_on": ["design_api"]},
    {"task_id": "test_limiter", "role": "test",
     "description": "Write tests for the limiter", "depends_on": ["impl_limiter"]},
])


def make_mock_llm(call_log: list) -> object:
    def llm(system: str, user: str) -> str:
        call_log.append({"system": system[:60], "user": user[:60]})
        if "Produce the JSON node array" in user:
            return _PLAN_JSON
        if "project lead" in system.lower():
            return "Built a rate limiter with design, implementation, and tests."
        role = "design"
        if "senior software engineer" in system.lower():
            role = "implement"
        elif "qa engineer" in system.lower():
            role = "test"
        return f"# {role} output\ncode here"
    return llm


# ── Planner 单元测试 ───────────────────────────────────────────────────────────

def test_extract_json_plain():
    nodes = _extract_json(_PLAN_JSON)
    assert len(nodes) == 3
    assert nodes[0]["task_id"] == "design_api"


def test_extract_json_with_fence():
    wrapped = f"Here is the plan:\n```json\n{_PLAN_JSON}\n```"
    nodes = _extract_json(wrapped)
    assert len(nodes) == 3


def test_nodes_to_manifests_tool_package():
    cfg = CodingConfig()
    nodes = json.loads(_PLAN_JSON)
    manifests = _nodes_to_manifests(nodes, cfg)
    assert {m.tool_package for m in manifests} == {"code"}
    roles = {m.tags.get("coding_role") for m in manifests if m.tags}
    assert roles == {"design", "implement", "test"}


def test_nodes_to_manifests_deps():
    cfg = CodingConfig()
    nodes = json.loads(_PLAN_JSON)
    manifests = _nodes_to_manifests(nodes, cfg)
    impl = next(m for m in manifests if m.task_id == "impl_limiter")
    assert "design_api" in impl.depends_on


def test_nodes_to_manifests_dedup():
    cfg = CodingConfig()
    nodes = json.loads(_PLAN_JSON) * 2  # 重复
    manifests = _nodes_to_manifests(nodes, cfg)
    ids = [m.task_id for m in manifests]
    assert len(ids) == len(set(ids))


# ── CodeResult 单元测试 ────────────────────────────────────────────────────────

def test_code_result_render_contains_artifacts():
    result = CodeResult.from_run(
        plan_id="pid-1",
        status="done",
        goal="test goal",
        outputs={"impl_limiter": "def run(): pass", "test_limiter": "assert True"},
        conclusion="All good.",
    )
    rendered = result.render()
    assert "impl_limiter" in rendered
    assert "test_limiter" in rendered
    assert "All good." in rendered


def test_code_result_empty_outputs():
    result = CodeResult.from_run(
        plan_id="pid-2",
        status="done",
        goal="empty",
        outputs={},
        conclusion="",
    )
    assert result.artifacts == {}
    assert "done" in result.render()


# ── CodeOrchestrator 端到端（无真�?LLM）─────────────────────────────────────

def test_orchestrator_full_run():
    call_log: list = []
    llm = make_mock_llm(call_log)
    cfg = CodingConfig(language="python", parallel_limit=2, use_react_action=False)
    orch = CodeOrchestrator(llm, cfg)
    result = asyncio.run(orch.run_coding("Implement an HTTP rate limiter middleware"))

    assert result.status == "done"
    assert set(result.artifacts.keys()) == {"design_api", "impl_limiter", "test_limiter"}
    assert result.summary  # replanner 汇总存�?


def test_orchestrator_plan_called_once():
    call_log: list = []
    llm = make_mock_llm(call_log)
    orch = CodeOrchestrator(llm, CodingConfig(use_react_action=False))
    asyncio.run(orch.run_coding("Write a calculator"))
    # Planner �?system prompt 包含 "coding task planner"（与其他角色 prompt 不同�?
    plan_calls = [c for c in call_log if "coding task planner" in c["system"].lower()]
    assert len(plan_calls) == 1


def test_orchestrator_mro():
    from agent.flow.base.dag_orchestrator import DagOrchestrator
    assert issubclass(CodeOrchestrator, DagOrchestrator)


def test_orchestrator_dispatch_bypasses_node_registry():
    """_dispatch_atomic 不经�?NodeRegistry/NodeRuntimeManager，运行时验证�?

    NodeRegistry 没有注册 executor_factory�?
    若路径经过父�?_dispatch_atomic �?build_executor()，会�?RuntimeError�?
    成功运行即证明走了子类覆写路径�?
    """
    call_log: list = []
    llm = make_mock_llm(call_log)
    orch = CodeOrchestrator(llm, CodingConfig(use_react_action=False))
    result = asyncio.run(orch.run_coding("Write a simple add function"))
    assert result.status == "done"


def test_config_default_tool_package():
    cfg = CodingConfig(default_tool_package="filesystem")
    assert cfg.default_tool_package == "filesystem"


def test_config_defaults():
    cfg = CodingConfig()
    assert cfg.language == "python"
    assert cfg.max_nodes == 8
    assert cfg.parallel_limit == 4
    assert cfg.default_tool_package == "code"
    assert cfg.use_react_action is False
