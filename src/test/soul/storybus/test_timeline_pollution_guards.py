"""时间轴污染防护：结构化残渣拒收 + 测试桩 journal 隔离。

背景（2026-09-17 控制台回归）：storybus 测试夹具经 ensure_story_runtime
落进真实 .react 时间轴（"第一拍""预约的内容"等），叠加叙事引擎把
compose 槽位 JSON（``{"intention":"rest","context":""}``）与提示词回声
当叙事，webui 回忆面板直接显示原始 JSON/夹具文本。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.life.virtual.narrative.engine import (
    _natural_narrative,
    looks_like_artifact,
    strip_think,
)
from agent.soul.wiring.story import (
    _MemoryTimelineJournal,
    _journal_for_soul,
    beat_from_subjective_event,
    ensure_story_runtime,
)


def test_strip_think_variants():
    assert strip_think("<think>推理</think>\nNARRATIVE]正文") == "NARRATIVE]正文"
    assert strip_think("<think>被截断的思考") == ""
    assert strip_think("没有思考的正文") == "没有思考的正文"


def test_looks_like_artifact_detects_json_and_echo():
    assert looks_like_artifact('{"intention":"rest","context":""}') is True
    assert looks_like_artifact('["beat"]') is True
    assert looks_like_artifact(", , , and tags. Key rules: - Second pers…") is True
    assert looks_like_artifact("她在黄昏散步时遇到一只猫") is False
    assert looks_like_artifact("") is False


def test_natural_narrative_rejects_artifact_body():
    # 模型未按标记输出、正文是 compose 槽位 JSON → 必须拒收而不是当叙事
    with pytest.raises(ValueError):
        _natural_narrative('{"intention":"rest","context":""}')
    # 正常标记输出不受影响
    narrative, _ = _natural_narrative(
        "[NARRATIVE]她把标本按科属排好。[/NARRATIVE] [EMOTION]安心[/EMOTION]"
    )
    assert "标本" in narrative


def test_beat_from_subjective_event_rejects_artifacts():
    assert beat_from_subjective_event({"hint": '{"intention":"rest"}'}) is None
    assert beat_from_subjective_event({"hint": ""}) is None
    draft = beat_from_subjective_event({"hint": "我刚为自己预约了一个体验时刻"})
    assert draft is not None and "预约" in draft.narrative


class _StubSoul:
    def __getattr__(self, name):
        raise AttributeError(name)


def test_ensure_story_runtime_isolates_stub_journals():
    stub = _StubSoul()
    rt = ensure_story_runtime(stub)
    assert isinstance(rt._journal, _MemoryTimelineJournal)
    # 桩上发射的 beat 不落真实时间轴
    rt._journal.append_event(session_id="live:main", text="第一拍", kind="story_intent")
    assert rt._journal.read("main")[0]["text"] == "第一拍"

    # 生产 SoulService 类名仍走全局时间轴
    class SoulService:  # 与生产类同名（_journal_for_soul 按类名识别）
        pass

    journal = _journal_for_soul(SoulService())
    assert not isinstance(journal, _MemoryTimelineJournal)
