"""导演注入门控 / ContextProvider / 软约束剧情 生产化单测（离线，无 LLM）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.speak.responders.request_driven.directors.unit_gate import (
    UnitGateDirector,
    resolve_unit_gate_variant,
)
from agent.soul.speak.responders.request_driven.orchestrator.context_provider import (
    ContextProviderRegistry,
    ScreenwriterContextProvider,
)
from agent.soul.speak.responders.request_driven.layers import RoleDynamicLayer, RolePromptLayers


class _FakeGateLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0

    def generate_json(self, *, system: str, user: str, session_id: str = "", director: str = "", turn_index=None) -> str:
        self.calls += 1
        return self.payload


class _FakeStateStore:
    def session(self, sid: str):
        from types import SimpleNamespace

        flow = SimpleNamespace(
            ready=True,
            inject_memory=True,
            memory_unit_ids=["m1", "m2"],
            inject_share=True,
            share_indices=[0, 1],
            pass_info=False,
            material_reason="screenwriter",
            chronicle="她整理着标本盒。",
        )
        arc = SimpleNamespace(ready=True, summary="一段博物学考察的故事线。")
        narrative = SimpleNamespace(scene_event="灯下整理标本。")
        return SimpleNamespace(plot_flow=flow, plot_arc=arc, narrative_card=narrative)


def test_resolve_unit_gate_variant():
    assert resolve_unit_gate_variant("v1") == "v1"
    assert resolve_unit_gate_variant("V2") == "v2"
    assert resolve_unit_gate_variant("") == "off"
    assert resolve_unit_gate_variant("junk") == "off"
    assert resolve_unit_gate_variant(None) == "off"


def test_unit_gate_filters_and_maps_ids():
    llm = _FakeGateLLM('{"memory_keep":[1],"share_keep":[],"reason":"只留相关"}')
    gate = UnitGateDirector(llm, variant="v2")
    gated = gate.filter_schedule(
        session_id="s1",
        user_text="你上次说的那本书呢",
        frame_text="用户：刚才聊到书",
        plot_context="故事线：整理标本",
        memory_texts=["用户养了猫", "用户之前聊过《森林报》"],
        share_texts=["想去采蘑菇"],
        memory_unit_ids=["m1", "m2"],
        share_indices=[0],
    )
    assert gated["inject_memory"] is True
    assert gated["memory_unit_ids"] == ["m2"]
    assert gated["inject_share"] is False
    assert gated["share_indices"] == []
    assert "unit_gate:v2" in gated["reason"]
    # 候选未变时缓存命中
    gate.filter_schedule(
        session_id="s1",
        user_text="你上次说的那本书呢",
        frame_text="用户：刚才聊到书",
        plot_context="故事线：整理标本",
        memory_texts=["用户养了猫", "用户之前聊过《森林报》"],
        share_texts=["想去采蘑菇"],
        memory_unit_ids=["m1", "m2"],
        share_indices=[0],
    )
    assert llm.calls == 1


def test_unit_gate_failure_keeps_none():
    llm = _FakeGateLLM("完全不是 JSON")
    gate = UnitGateDirector(llm, variant="v1")
    assert (
        gate.filter_schedule(
            user_text="hi",
            frame_text="",
            plot_context="",
            memory_texts=["m"],
            share_texts=[],
            memory_unit_ids=["m1"],
            share_indices=[],
        )
        is None
    )
    assert gate.errors == 1
    # LLM 缺席：同样返回 None（调用方保持编剧提案）
    assert UnitGateDirector(None, variant="v1").filter_schedule(
        user_text="hi",
        frame_text="",
        plot_context="",
        memory_texts=["m"],
        share_texts=[],
        memory_unit_ids=["m1"],
        share_indices=[],
    ) is None


def test_unit_gate_variant_prompt_difference():
    v1 = UnitGateDirector(_FakeGateLLM("{}"), variant="v1")
    v2 = UnitGateDirector(_FakeGateLLM("{}"), variant="v2")
    assert v1.variant == "v1" and v2.variant == "v2"
    # v2 剧情对齐：喂 plot_context 后 LLM 的 user 里应含剧情
    seen: dict[str, str] = {}

    class _Spy(_FakeGateLLM):
        def generate_json(self, *, system, user, **kw):
            seen["user"] = user
            return super().generate_json(system=system, user=user, **kw)

    spy = _Spy('{"memory_keep":[],"share_keep":[]}')
    UnitGateDirector(spy, variant="v2").filter_schedule(
        user_text="在吗",
        frame_text="",
        plot_context="她在灯下整理标本",
        memory_texts=["记忆A"],
        share_texts=["分享B"],
        memory_unit_ids=["m1"],
        share_indices=[0],
    )
    assert "她在灯下整理标本" in seen["user"]
    seen.clear()
    UnitGateDirector(_FakeGateLLM('{"memory_keep":[],"share_keep":[]}'), variant="v1").filter_schedule(
        user_text="在吗",
        frame_text="",
        plot_context="她在灯下整理标本",
        memory_texts=["记忆A"],
        share_texts=["分享B"],
        memory_unit_ids=["m1"],
        share_indices=[0],
    )
    # v1 不看剧情（保持旧行为）
    assert "她在灯下整理标本" not in seen.get("user", "")


def test_context_provider_registry_priority_and_fallback():
    store = _FakeStateStore()
    registry = ContextProviderRegistry(state_store=store)
    assert registry.kinds() == ("screenwriter",)

    schedule = registry.material_schedule("s1")
    assert schedule["inject_memory"] is True
    assert schedule["memory_unit_ids"] == ["m1", "m2"]
    assert schedule["provider_kind"] == "screenwriter"

    plot = registry.plot_materials("s1")
    assert "标本" in plot["plot_flow_text"]
    assert "故事线" in plot["plot_outline_text"]

    # 游戏 provider 接管材料调度（注册序在前优先）
    class _GameProvider:
        kind = "game"

        def snapshot(self, session_id: str):
            return {
                "kind": self.kind,
                "material_schedule": {
                    "inject_memory": True,
                    "memory_unit_ids": ["g1"],
                    "inject_share": False,
                    "share_indices": [],
                },
                "plot_outline_text": "游戏世界剧情",
            }

    registry.register(_GameProvider())
    schedule = registry.material_schedule("s1")
    assert schedule["memory_unit_ids"] == ["m1", "m2"]  # 编剧在前，仍优先

    registry.unregister("screenwriter")
    schedule = registry.material_schedule("s1")
    assert schedule["memory_unit_ids"] == ["g1"]
    assert schedule["provider_kind"] == "game"


def test_screenwriter_provider_snapshot_shape():
    snap = ScreenwriterContextProvider(_FakeStateStore()).snapshot("s1")
    assert snap["kind"] == "screenwriter"
    assert snap["material_schedule"]["inject_share"] is True
    assert snap["scene_event"]


def test_soft_plot_headers_are_default():
    layers = RolePromptLayers(
        static=None,  # type: ignore[arg-type]
        dynamic=RoleDynamicLayer(
            plot_outline_text="故事线正文",
            plot_flow_text="此刻情景正文",
        ),
        session_id="s1",
    )
    rendered = layers.render_system_extra()
    assert "参考剧情（软约束" in rendered
    assert "对方在剧情中的位置" in rendered
    assert "客观材料" not in rendered


def test_writer_user_memory_enrichment_and_gate_hook():
    from agent.soul.speak.responders.request_driven.screenwriter.writer import Screenwriter

    searched: list[tuple] = []

    def _search(mode: str, **kwargs):
        searched.append((mode, kwargs))
        return [
            {"fact": "对方在准备考试", "id": "u1"},
            {"fact": "对方喜欢雨天散步", "id": "u2"},
        ]

    gate_calls: list[dict] = []

    def _gate(**kwargs):
        gate_calls.append(kwargs)
        return {
            "inject_memory": False,
            "memory_unit_ids": [],
            "inject_share": True,
            "share_indices": [0],
            "reason": "unit_gate:v1",
        }

    writer = Screenwriter(material_gate=_gate, memory_search=_search)

    materials = {"last_user_text": "最近在忙考试"}
    enriched = writer._enrich_user_memory("s1", materials)
    assert enriched["dynamic_user_memory_texts"] == [
        "对方在准备考试",
        "对方喜欢雨天散步",
    ]
    assert searched[0][0] == "hybrid"
    # 缓存：同 query 二次不检索
    writer._enrich_user_memory("s1", {"last_user_text": "最近在忙考试"})
    assert len(searched) == 1

    from types import SimpleNamespace

    flow = SimpleNamespace(
        inject_memory=True,
        memory_unit_ids=["m1"],
        inject_share=False,
        share_indices=[],
        pass_info=False,
        set_calls=[],
    )

    def _set_schedule(**kwargs):
        flow.set_calls.append(kwargs)

    flow.set_material_schedule = _set_schedule
    state = SimpleNamespace(
        plot_flow=flow,
        plot_arc=None,
        last_real_user_text="最近在忙考试",
        notes=[],
    )
    writer._apply_material_gate(
        state,
        {
            "dynamic_memory_texts": ["一条记忆"],
            "dynamic_share_texts": ["想分享的事"],
            "recent_turns": ["用户：最近在忙考试"],
        },
        session_id="s1",
    )
    assert len(gate_calls) == 1
    assert gate_calls[0]["memory_texts"] == ["一条记忆"]
    assert flow.set_calls[-1]["inject_share"] is True
    assert flow.set_calls[-1]["inject_memory"] is False
