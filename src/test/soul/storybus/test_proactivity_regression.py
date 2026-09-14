"""回归用例：主动性相关（single-stream 用户的两个验收主题）。

主题一 · 时间帧单开口不变量：
  speak 底层约定一个时间帧至多开口一次；沉默、改期（预约）都必须在
  当前帧内完成裁决——不留跨帧悬案。

主题二 · 主动会话工作流在线：
  life beat → 角色决策 → enqueue_agent_outbound 主动出站（payload 契约）。

附带 · 旧链路断供开关（R6.3）：story_autonomy 默认开启。

跑法：cd src && python -m pytest test/soul/storybus/test_proactivity_regression.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.speak.responders.request_driven.character.beat_policy import FrameGate  # noqa: E402
from agent.soul.speak.story_autonomy import story_autonomy_enabled  # noqa: E402
from agent.soul.storybus import BeatDraft, PerformanceHint  # noqa: E402
from agent.soul.wiring.story import ensure_story_runtime  # noqa: E402

_TERMINAL = {"performed", "expired", "declined"}
_RESOLVED = _TERMINAL | {"held"}   # 帧内收敛：不允许停留在 pending


class _SoulStub:
    def __getattr__(self, name):
        raise AttributeError(name)


class _FakeSpeakSoul:
    """speak 就绪的假 soul：记录 enqueue 载荷，恒投递成功。"""

    class _Speak:
        def __init__(self, outer):
            self.outer = outer

        def enqueue_agent_outbound(self, payload):
            outer = self.outer
            outer.payloads.append(dict(payload))
            outer.open_times.append(outer.clock())
            return {"ok": True, "delivered": True}

    payloads: list = []
    open_times: list = []
    clock = staticmethod(lambda: 0.0)

    def __init__(self):
        type(self).payloads = []
        type(self).open_times = []

    def _ensure_speak_service(self):
        return self._Speak(self)


def _eager_draft(narrative="她想说说今天的事"):
    return BeatDraft(
        narrative=narrative,
        channels=("main",),
        hint=PerformanceHint(urgency="eager", share_desire=0.9),
    )


# ── 主题一：时间帧单开口 ────────────────────────────────────────────────────

def test_frame_gate_one_opening_per_window():
    now = {"t": 0.0}
    gate = FrameGate(window_sec=5.0, clock=lambda: now["t"])
    assert gate.try_open("main") is True          # 帧内首次开口
    assert gate.try_open("main") is False         # 同帧第二拍拒绝
    assert gate.try_open("other") is True         # 跨渠道互不占用
    now["t"] += 5.0
    assert gate.try_open("main") is True          # 下一帧恢复


def test_same_frame_two_beats_exactly_one_performed():
    soul = _FakeSpeakSoul()
    rt = ensure_story_runtime(soul)
    rt.ensure_inbox()
    # 帧时钟冻结在同一窗口内
    rt._gate.__init__(window_sec=5.0, clock=lambda: 100.0)

    assert rt.emit_drafts([_eager_draft("第一拍"), _eager_draft("第二拍")]) == 2

    # 恰好一次开口
    assert len(soul.payloads) == 1
    assert soul.payloads[0]["message"] == "第一拍"
    # 第二拍帧内裁决为改期（suppressed → held），不是悬案
    assert len(rt.ledger.held()) >= 1
    for bid in rt.ledger._beats:
        state = rt.ledger.state_of(bid)
        assert state in _RESOLVED, f"帧内未收敛: {state}"


def test_all_beats_resolve_within_frame():
    """帧内收敛不变量：任何发射批次结束后，无 beat 停留在 pending。"""
    soul = _FakeSpeakSoul()
    rt = ensure_story_runtime(soul)
    rt.ensure_inbox()
    rt.emit_drafts([
        _eager_draft("高欲望"),
        BeatDraft(narrative="低欲望", channels=("main",),
                  hint=PerformanceHint(urgency="calm", share_desire=0.2)),
    ])
    assert rt.ledger.pending() == []
    for b in rt.ledger._beats.values():
        assert rt.ledger.state_of(b.beat_id) in _RESOLVED


# ── 主题二：主动会话工作流 ──────────────────────────────────────────────────

def test_proactive_session_payload_contract():
    soul = _FakeSpeakSoul()
    rt = ensure_story_runtime(soul)
    rt.ensure_inbox()
    rt.emit_drafts([_eager_draft("主动开口的内容")])

    assert len(soul.payloads) == 1
    p = soul.payloads[0]
    assert p["source"] == "story"
    assert p["agent_initiated"] is True
    assert p["session_id"] == "live:main" and p["channel_id"] == "main"
    assert p["message"] == "主动开口的内容"
    assert p.get("beat_id")


def test_held_beat_rescheduled_next_tick_performs():
    """预约（改期）：speak 未就绪 → held → 下一剧情拍重投 → 就绪后开口。"""
    # 第一阶段：speak 缺席 → suppressed → held
    soul1 = _SoulStub()
    rt = ensure_story_runtime(soul1)
    rt.emit_drafts([_eager_draft("预约的内容")])
    held = rt.ledger.held()
    assert len(held) == 1

    # 第二阶段：同一 soul 恢复 speak（模拟稍后连上）
    class _Restored(_SoulStub):
        def _ensure_speak_service(self):
            return _FakeSpeakSoul._Speak(_FakeSpeakSoul())

    # 同一实例替换方法：直接给 soul1 挂上 speak
    soul1._ensure_speak_service = lambda: _FakeSpeakSoul._Speak(_FakeSpeakSoul())  # type: ignore[method-assign]
    rt._gate.__init__(window_sec=5.0, clock=lambda: 0.0)

    moved = rt.redeliver_held()
    assert moved == 1
    # 旧条目归档（declined 终态），新 beat 已 performed
    assert rt.ledger.state_of(held[0].beat_id) == "declined"
    performed = [b for b in rt.ledger._beats.values()
                 if rt.ledger.state_of(b.beat_id) == "performed"]
    assert len(performed) == 1 and performed[0].narrative == "预约的内容"


# ── 断供开关（R6.3） ────────────────────────────────────────────────────────

def test_story_autonomy_flag_default_on(monkeypatch=None):
    assert story_autonomy_enabled() is True
    import os
    old = os.environ.get("ANIMUS_STORY_AUTONOMY")
    try:
        os.environ["ANIMUS_STORY_AUTONOMY"] = "0"
        assert story_autonomy_enabled() is False   # 应急回滚通道可用
    finally:
        if old is None:
            os.environ.pop("ANIMUS_STORY_AUTONOMY", None)
        else:
            os.environ["ANIMUS_STORY_AUTONOMY"] = old
