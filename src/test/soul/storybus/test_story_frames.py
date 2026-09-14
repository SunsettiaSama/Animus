"""P3 后端帧测试：story_card / story_progress WS 帧发射（R8/§8）。

跑法：cd src && python -m pytest test/soul/storybus/test_story_frames.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.wiring.story import ensure_story_runtime  # noqa: E402


class _FakePort:
    def __init__(self):
        self.events = []

    def emit(self, session_id, event):
        self.events.append((session_id, event.kind, dict(event.meta)))


class _FakeStreamSpeak:
    """speak 就绪 + stream_port 可用的假 soul。"""

    class _Outbound:
        def __init__(self, port):
            self.stream_port = port

    class _SpeakOutboundRouter:
        def __init__(self, port):
            self.stream_port = port

    def __init__(self):
        self.port = _FakePort()
        self.speak_outbound = self._SpeakOutboundRouter(self.port)

    def _ensure_speak_service(self):
        return object()  # 桥的 perform 路径不在此测


def test_open_and_advance_card_emit_ws_frames():
    soul = _FakeStreamSpeak()
    rt = ensure_story_runtime(soul)

    card = rt.open_card("第一幕：整理旧居")
    kinds = [k for _, k, _ in soul.port.events]
    assert kinds == ["story_card"]
    sid, kind, meta = soul.port.events[0]
    assert sid == "live:main" and meta["outline"].startswith("第一幕")

    rt.advance_card(card.card_id, current="发现一封信", upcoming=["读信"])
    kinds = [k for _, k, _ in soul.port.events]
    assert kinds == ["story_card", "story_progress"]
    _, kind2, meta2 = soul.port.events[1]
    assert kind2 == "story_progress" and meta2["current"] == "发现一封信"
    assert meta2["upcoming"] == ["读信"]

    # 大纲冻结：进度推进后 outline 不变
    assert rt.cards.get(card.card_id).outline.startswith("第一幕")


def test_frames_dropped_without_stream_port():
    class _NoPortSoul:
        class _R:
            stream_port = None

        speak_outbound = _R()

        def _ensure_speak_service(self):
            return object()

        def __getattr__(self, name):
            raise AttributeError(name)

    rt = ensure_story_runtime(_NoPortSoul())
    card = rt.open_card("无连接时开卡")          # 不抛错（可丢语义）
    assert rt.advance_card(card.card_id, current="推进") is not None
