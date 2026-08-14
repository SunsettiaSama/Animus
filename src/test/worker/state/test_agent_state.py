from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from worker.state.memory_distill import MemoryDistillChain
from worker.state.schema import (
    MEMORY_PORTRAIT_SLOT,
    REFLECTION_PORTRAIT_SLOT,
    WORKER_PORTRAIT_SLOT,
    MAX_REFLECTION_PORTRAIT_CHARS,
    MemoryPortraitState,
    ReflectionPortraitState,
    WorkerPortraitState,
)
from worker.state.service import AgentStateService
from worker.state.store import AgentStateStore
from worker.state.work_reflection import TaskResultQuality, TurnTaskGraph


class _FakeLLM:
    def __init__(self) -> None:
        self.calls = 0
        self.messages: list[list] = []

    def generate_messages(self, messages):
        self.calls += 1
        self.messages.append(messages)
        system = str(messages[0].content)
        if "记忆画像蒸馏器" in system:
            return "你最近持续关注 Worker 状态旁路及其验证结果。"
        return (
            "本轮执行暴露出验证证据不足的问题：虽然完成了动作，但结果摘要没有覆盖边界条件。"
            "旧反思中关于先定义完成标准的要求仍未完全落实，应继续保留。"
            "下一轮必须在首个动作前写明可验证标准，在工具返回后区分成功、部分完成和失败，"
            "交付前运行与改动风险相称的测试，并在结论中明确剩余风险。"
            "本轮没有证据表明任务拆分本身存在方向性错误，因此不应为了追求形式而增加无意义步骤；"
            "真正需要修正的是将验证推迟到交付以后。后续还应检查并行动作是否各自得到结果，"
            "任何空返回或模糊成功信息都只能标记为部分完成，必须补充检查后才能作为最终结论。"
        )


class _FakeMemory:
    def search(self, mode: str, **kwargs):
        return [
            {"id": "m1", "fact": "用户正在实现 Worker state"},
            {"id": "m1", "fact": "重复内容"},
        ]


class _FakeMedium:
    def render(self) -> str:
        return "最近完成了状态模块的初步接线。"


def test_store_persists_three_parallel_slots(tmp_path: Path):
    store = AgentStateStore(tmp_path)
    store.commit(WorkerPortraitState(content="稳定工作者画像"))
    store.commit(ReflectionPortraitState(content="跨轮反思", turn_count=2))
    store.commit(
        MemoryPortraitState(
            narrative="中长期记忆画像",
            source_revision="memory-r1",
        )
    )

    loaded = AgentStateStore(tmp_path).snapshot()
    assert loaded.worker_portrait_text() == "稳定工作者画像"
    assert loaded.reflection_portrait_text() == "跨轮反思"
    assert loaded.memory_portrait_text() == "中长期记忆画像"
    assert loaded.slot(WORKER_PORTRAIT_SLOT) is not None
    assert loaded.slot(REFLECTION_PORTRAIT_SLOT) is not None
    assert loaded.slot(MEMORY_PORTRAIT_SLOT) is not None


def test_store_rejects_old_root_schema(tmp_path: Path):
    path = tmp_path / "agent_state.json"
    path.write_text(
        json.dumps({"schema_version": "agent_state_v1", "slots": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported agent state schema"):
        AgentStateStore(tmp_path)


def test_snapshot_is_immutable(tmp_path: Path):
    store = AgentStateStore(tmp_path)
    snapshot = store.snapshot()
    store.commit(ReflectionPortraitState(content="新的反思", turn_count=1))
    assert snapshot.reflection_portrait_text() != "新的反思"
    assert store.snapshot().reflection_portrait_text() == "新的反思"


def test_memory_distill_remains_parallel_and_caches(tmp_path: Path):
    store = AgentStateStore(tmp_path)
    llm = _FakeLLM()
    chain = MemoryDistillChain(
        store,
        llm=llm,
        memory=_FakeMemory(),
        medium=_FakeMedium(),
        persona_revision="p1",
    )
    first = chain.run()
    second = chain.run()
    assert first.refreshed is True
    assert second.reason == "cache_hit"
    assert llm.calls == 1
    assert store.snapshot().memory_portrait_text()


def test_task_graph_parallel_edges_and_result_quality():
    graph = TurnTaskGraph("检查两个模块")
    graph.record_actions(
        [
            {"action": "read_file", "args": {"path": "a.py"}},
            {"action": "run_test", "args": {"path": "b.py"}},
        ],
        ["文件读取成功", "ERROR: test failed"],
    )
    nodes = graph.nodes
    assert nodes[-2].quality == TaskResultQuality.success
    assert nodes[-1].quality == TaskResultQuality.failed
    root = nodes[0].node_id
    targets = {edge.target for edge in graph.edges if edge.source == root}
    assert targets == {nodes[-2].node_id, nodes[-1].node_id}
    assert len(graph.render()) <= 500


def test_task_graph_recursively_distills_nodes_and_edges():
    graph = TurnTaskGraph("执行一个包含很多步骤的复杂任务")
    for index in range(18):
        graph.record_actions(
            [{"action": f"tool_{index}", "args": {"value": index}}],
            [f"第 {index} 个动作成功，返回了可验证证据 " + "x" * 80],
        )
    rendered = graph.render()
    assert len(rendered) <= 500
    assert any(node.archived_count > 1 for node in graph.nodes)
    node_ids = {node.node_id for node in graph.nodes}
    assert all(
        edge.source in node_ids and edge.target in node_ids
        for edge in graph.edges
    )


def test_task_graph_rejects_missing_action_observation():
    graph = TurnTaskGraph("检查动作与结果数量")
    with pytest.raises(ValueError, match="one observation per action"):
        graph.record_actions(
            [{"action": "first"}, {"action": "second"}],
            ["only one result"],
        )


def test_work_reflection_turns_are_isolated(tmp_path: Path):
    service = AgentStateService(state_dir=tmp_path, llm=_FakeLLM())
    first = service.begin_turn("任务一")
    second = service.begin_turn("任务二")
    first.task_graph.record_actions([{"action": "a"}], ["success"])
    assert "action=a" in first.task_graph.render()
    assert "action=a" not in second.task_graph.render()


def test_reflection_agent_reads_modifies_and_commits(tmp_path: Path):
    llm = _FakeLLM()
    service = AgentStateService(state_dir=tmp_path, llm=llm)
    state = service.begin_turn("实现旁路")
    state.task_graph.record_actions(
        [{"action": "edit", "args": {}}],
        ["partial: 尚未测试"],
    )
    result = service.reflect(
        question="实现旁路",
        answer="已完成",
        steps=({"action": "edit", "observation": "partial: 尚未测试"},),
        task_graph=state.task_graph.render(),
        terminal_status="finished",
    )
    assert result.turn_count == 1
    assert len(result.content) <= MAX_REFLECTION_PORTRAIT_CHARS
    assert service.snapshot().reflection_portrait == result
    assert llm.calls == 1


def test_concurrent_reflections_are_serialized(tmp_path: Path):
    llm = _FakeLLM()
    service = AgentStateService(state_dir=tmp_path, llm=llm)

    def reflect(index: int) -> None:
        service.reflect(
            question=f"q{index}",
            answer=f"a{index}",
            steps=(),
            task_graph=TurnTaskGraph(f"q{index}").render(),
            terminal_status="finished",
        )

    threads = [threading.Thread(target=reflect, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert service.snapshot().reflection_portrait.turn_count == 6
    assert llm.calls == 6


def test_work_service_passes_state_service_to_worker(tmp_path: Path, monkeypatch):
    from worker.work.adapter import WorkerAdapter
    from worker.work.service import WorkerWorkService

    state_service = AgentStateService(state_dir=tmp_path, llm=_FakeLLM())
    work = WorkerWorkService(
        llm_cfg_path="config/llm_core/config.yaml",
        agent_state_service=state_service,
        confirmation_timeout_sec=30,
    )
    captured: dict = {}

    def fake_run(
        self,
        instruction,
        *,
        event_callback=None,
        soul=None,
        agent_state_service=None,
        sandbox=None,
        risk_gate=None,
        **kwargs,
    ):
        captured["service"] = agent_state_service
        return {
            "answer": "done",
            "step_count": 0,
            "steps": [],
            "steps_log": [],
        }

    monkeypatch.setattr(WorkerAdapter, "run_single_task", fake_run)
    from config.agent.risk_config import RiskConfig
    from infra.sandbox import SandboxManager
    from worker.tools.risk.gate import RiskGate

    sandbox = SandboxManager()
    sandbox._cfg.workspace_root = str(tmp_path / "ws")
    sandbox.start()
    work.bind_runtime(
        sandbox=sandbox,
        risk_gate=RiskGate.from_config(RiskConfig()),
    )
    signal = work.maybe_signal(
        "你帮我实现 worker state",
        session_id="s1",
        channel_id="c1",
        gen_id="g1",
    )
    assert signal is not None
    work.submit_intent(signal)
    work.handle_confirmation(signal.work_id, approved=True, soul=None)
    work._threads[signal.work_id].join(timeout=2)
    assert captured["service"] is state_service


def test_delegate_passes_work_reflection_sidecar():
    from worker.tools.skill.delegate_task import DelegateTaskSkill

    state_service = object()
    captured: dict = {}

    class Runner:
        def run_sync(self, instruction, profile, llm_path, **kwargs):
            captured.update(kwargs)
            return {"answer": "done"}

    skill = DelegateTaskSkill(
        runner=Runner(),
        cfg=SimpleNamespace(
            llm_cfg_path="llm.yaml",
        ),
        agent_state_service=state_service,
    )
    assert skill.execute("sub task") == "done"
    assert captured["agent_state_service"] is state_service


def test_worker_flow_public_export_uses_worker_orchestrator():
    from worker.flow import FlowOrchestrator
    from worker.flow.cluster import FlowOrchestrator as ClusterFlowOrchestrator

    assert FlowOrchestrator is ClusterFlowOrchestrator
    assert FlowOrchestrator.__module__ == "worker.flow.cluster.orchestrator"


def test_manifest_executor_passes_work_reflection_sidecar(monkeypatch):
    from worker.flow.base.components.node_spec import NodeManifest
    from worker.flow.base.defaults import SubAgentManifestExecutor
    from worker.runner import SubAgentRunner

    state_service = object()
    captured: dict = {}

    def fake_run(self, instruction, profile, llm_path, **kwargs):
        captured.update(kwargs)
        return {"answer": "manifest done"}

    monkeypatch.setattr(SubAgentRunner, "run_sync", fake_run)
    executor = SubAgentManifestExecutor(
        "llm.yaml",
        agent_state_service=state_service,
    )
    output = executor.run(
        NodeManifest(task_id="n1", description="execute manifest"),
        {},
    )
    assert output == "manifest done"
    assert captured["agent_state_service"] is state_service
r'''
"""Unit tests for worker.state typed Agent State + memory_distill fallback."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from worker.state.memory_distill import MemoryDistillChain, gather_portrait_source
from worker.state.schema import MEMORY_PORTRAIT_SLOT, MemoryPortraitState
from worker.state.service import AgentStateService
from worker.state.store import AgentStateStore


class _FakeMemory:
    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = list(items or [])
        self.calls: list[tuple[str, dict]] = []

    def search(self, mode: str, **kwargs):
        self.calls.append((mode, dict(kwargs)))
        if mode == "recent":
            return list(self.items)
        if mode == "hybrid":
            return list(self.items[:2])
        return []


class _FakeMedium:
    def __init__(self, text: str) -> None:
        self._text = text

    def render(self) -> str:
        return self._text


class _FakeLLM:
    def __init__(self, text: str = "你最近持续关注 WebUI 重构，并记得用户偏爱简洁接口。") -> None:
        self.text = text
        self.calls = 0

    def generate_messages(self, messages):
        self.calls += 1
        return self.text


def test_store_persist_and_reload(tmp_path: Path):
    store = AgentStateStore(tmp_path)
    slot = MemoryPortraitState(
        narrative="你记得用户在推进 worker state。",
        source_revision="rev-1",
        source_unit_ids=("u1", "u2"),
        source_medium_chars=12,
    )
    store.commit(slot)

    store2 = AgentStateStore(tmp_path)
    loaded = store2.read(MEMORY_PORTRAIT_SLOT)
    assert isinstance(loaded, MemoryPortraitState)
    assert loaded.narrative.startswith("你记得")
    assert loaded.source_revision == "rev-1"
    assert loaded.source_unit_ids == ("u1", "u2")


def test_snapshot_is_atomic_and_immutable(tmp_path: Path):
    store = AgentStateStore(tmp_path)
    store.commit(
        MemoryPortraitState(narrative="snap-a", source_revision="r1")
    )
    snap = store.snapshot()
    store.commit(
        MemoryPortraitState(narrative="snap-b", source_revision="r2")
    )
    assert snap.memory_portrait_text() == "snap-a"
    assert store.snapshot().memory_portrait_text() == "snap-b"


def test_gather_dedupe_and_revision():
    mem = _FakeMemory(
        [
            {"id": "a", "fact": "用户要求实现 state"},
            {"id": "a", "fact": "重复"},
            {"id": "b", "fact": "用户要求实现 state"},
            {"id": "c", "narrative": "你完成了意图匹配"},
        ]
    )
    medium = _FakeMedium("中期：你在整理 worker 模块。")
    bundle = gather_portrait_source(
        memory=mem,
        medium=medium,
        persona_revision="p1",
        hybrid_query="state",
    )
    assert not bundle.is_empty
    assert "a" in bundle.unit_ids
    assert "c" in bundle.unit_ids
    assert bundle.unit_ids.count("a") == 1
    assert bundle.medium_text.startswith("中期")
    assert bundle.source_revision.startswith("p1|")

    again = gather_portrait_source(
        memory=mem,
        medium=medium,
        persona_revision="p1",
        hybrid_query="state",
    )
    assert again.source_revision == bundle.source_revision


def test_fallback_chain_cache_hit_skips_llm(tmp_path: Path):
    store = AgentStateStore(tmp_path)
    mem = _FakeMemory([{"id": "u1", "fact": "你记得确认后执行任务"}])
    medium = _FakeMedium("中期摘要")
    llm = _FakeLLM()
    chain = MemoryDistillChain(
        store,
        llm=llm,
        memory=mem,
        medium=medium,
        persona_revision="p",
    )
    assert chain.chain_role == "fallback"
    first = chain.run()
    assert first.refreshed is True
    assert first.reason == "derived"
    assert llm.calls == 1

    second = chain.run()
    assert second.refreshed is False
    assert second.reason == "cache_hit"
    assert llm.calls == 1


def test_fallback_chain_empty_source(tmp_path: Path):
    store = AgentStateStore(tmp_path)
    llm = _FakeLLM()
    chain = MemoryDistillChain(
        store,
        llm=llm,
        memory=_FakeMemory([]),
        medium=_FakeMedium(""),
    )
    result = chain.run()
    assert result.refreshed is False
    assert result.reason == "empty_source"
    assert llm.calls == 0


def test_service_refresh_fallback_and_concurrent_snapshot(tmp_path: Path):
    llm = _FakeLLM("你记得用户偏好中文交互，并关注 state 抽象。")
    mem = _FakeMemory([{"id": "m1", "fact": "偏好中文"}])

    class _Soul:
        class memory:
            class api:
                @staticmethod
                def search(mode: str, **kwargs):
                    return mem.search(mode, **kwargs)

        class persona:
            class service:
                @staticmethod
                def portrait_revision():
                    return "rev-x"

                @staticmethod
                def bias_query(query: str):
                    return query

        @staticmethod
        def get_persona_snapshot(session_id: str = "tao"):
            return {
                "persona_distill": {
                    "slices": {"memory_anchor": "你是稳重的执行者。"}
                }
            }

    svc = AgentStateService(
        state_dir=tmp_path,
        llm=llm,
        soul=_Soul(),
        medium_dir=None,
    )
    assert svc.FALLBACK_CHAIN_ID == "memory_distill"
    result = svc.refresh_fallback()
    assert result.refreshed is True
    text = svc.snapshot().memory_portrait_text()
    assert "state" in text or "中文" in text

    snaps: list[str] = []

    def _reader():
        snaps.append(svc.snapshot().memory_portrait_text())

    threads = [threading.Thread(target=_reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(s for s in snaps)


def test_work_path_reads_snapshot_and_async_fallback_refresh(tmp_path: Path, monkeypatch):
    from worker.work.adapter import WorkerAdapter
    from worker.work.service import WorkerWorkService

    llm = _FakeLLM("你记得用户要你跑任务后刷新画像。")
    mem = _FakeMemory([{"id": "w1", "fact": "任务后刷新"}])

    class _Soul:
        class memory:
            class api:
                @staticmethod
                def search(mode: str, **kwargs):
                    return mem.search(mode, **kwargs)

        class persona:
            class service:
                @staticmethod
                def portrait_revision():
                    return "rev-w"

                @staticmethod
                def bias_query(query: str):
                    return query

        @staticmethod
        def get_persona_snapshot(session_id: str = "tao"):
            return {}

    class _Runner:
        def __init__(self):
            self.jobs = []

        def submit(self, name, fn, *args, on_error=None):
            self.jobs.append(name)
            return fn(*args)

    task_runner = _Runner()
    state_svc = AgentStateService(
        state_dir=tmp_path,
        llm=llm,
        soul=_Soul(),
        task_runner=task_runner,
    )
    state_svc.refresh_fallback()
    before_calls = llm.calls

    work = WorkerWorkService(
        llm_cfg_path="config/llm_core/config.yaml",
        agent_state_service=state_svc,
        confirmation_timeout_sec=30,
    )
    captured: dict = {}

    def _fake_run(self, instruction, *, event_callback=None, soul=None, agent_state=None):
        captured["agent_state"] = agent_state
        captured["instruction"] = instruction
        return {
            "answer": "done",
            "step_count": 1,
            "steps": [],
            "steps_log": [],
            "runner": "worker.sub_agent",
            "profile": "executor",
        }

    monkeypatch.setattr(WorkerAdapter, "run_single_task", _fake_run)

    sig = work.maybe_signal(
        "你帮我整理一下 state 模块",
        session_id="s1",
        channel_id="c1",
        gen_id="g1",
    )
    assert sig is not None
    work.submit_intent(sig)
    result = work.handle_confirmation(sig.work_id, approved=True, soul=_Soul())
    assert result["ok"] is True

    thread = work._threads[sig.work_id]
    thread.join(timeout=2)
    assert captured["agent_state"] is not None
    assert captured["agent_state"].memory_portrait_text()
    assert "worker_state_memory_distill" in task_runner.jobs
    assert llm.calls >= before_calls
'''
