"""storybus 契约单测（需求 §9：幂等/保鲜/ack 状态机/signal/进度）。

跑法：cd src && python -m pytest test/soul/storybus/test_storybus.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.life.story import BeatLedger, CallableBeatSource, StoryOutbox, StoryScheduler  # noqa: E402
from agent.soul.storybus import (  # noqa: E402
    BeatAck,
    BeatAckStatus,
    BeatDraft,
    LifeStoryBeat,
    PerformanceHint,
    StorySignal,
)
from agent.soul.wiring.story import InProcessStoryBus, StoryRuntime  # noqa: E402


def _beat(beat_id: str = "b1", valid_until: str = "", channels=("main",)) -> LifeStoryBeat:
    return LifeStoryBeat(
        beat_id=beat_id,
        narrative="她在窗边想起了一件旧事",
        channels=channels,
        hint=PerformanceHint(valid_until=valid_until),
    )


# ── 总线 ────────────────────────────────────────────────────────────────────

def test_bus_delivers_and_routes_ack_signal_progress():
    bus = InProcessStoryBus()
    beats, acks, signals, progress = [], [], [], []
    bus.bind_inbox(on_beat=beats.append, on_progress=progress.append)
    bus.bind_life_side(ack_receiver=acks.append, signal_inbox=signals.append)

    assert bus.deliver_beat(_beat()) is True
    assert beats == [] or beats[0].beat_id == "b1"

    bus.send_ack(BeatAck("b1", "main", BeatAckStatus.performed))
    bus.send_signal(StorySignal("live:main", "main", "用户聊到了旧照片"))
    from agent.soul.storybus import StoryProgressSync
    bus.sync_progress(StoryProgressSync(card_id="c1", current="第二幕"))

    assert len(beats) == 1 and len(acks) == 1 and len(signals) == 1 and len(progress) == 1


def test_bus_dedups_by_beat_id():
    bus = InProcessStoryBus()
    beats: list[LifeStoryBeat] = []
    bus.bind_inbox(on_beat=beats.append)
    assert bus.deliver_beat(_beat()) is True
    assert bus.deliver_beat(_beat()) is False   # 幂等：重复投递拒收
    assert len(beats) == 1


def test_bus_expired_beat_not_forwarded_but_acked_expired():
    bus = InProcessStoryBus()
    beats, acks = [], []
    bus.bind_inbox(on_beat=beats.append)
    bus.bind_life_side(ack_receiver=acks.append)

    expired = _beat(valid_until="2000-01-01T00:00:00+00:00")
    assert bus.deliver_beat(expired) is False
    assert beats == []
    assert len(acks) == 1 and acks[0].status_value() == BeatAckStatus.expired.value


def test_bus_inbox_exception_isolated():
    bus = InProcessStoryBus()
    def boom(beat):
        raise RuntimeError("inbox broken")
    bus.bind_inbox(on_beat=boom)
    assert bus.deliver_beat(_beat()) is False  # 不抛出、返回 False


def test_bus_no_inbox_returns_false():
    bus = InProcessStoryBus()
    assert bus.deliver_beat(_beat()) is False


# ── 账本状态机 ──────────────────────────────────────────────────────────────

def test_ledger_terminal_states():
    ledger = BeatLedger()
    ledger.record(_beat("b1"))
    ledger.receive_ack(BeatAck("b1", "main", BeatAckStatus.performed))
    assert ledger.state_of("b1") == "performed"
    # 终态后再收 ack 忽略
    ledger.receive_ack(BeatAck("b1", "main", BeatAckStatus.silenced))
    assert ledger.state_of("b1") == "performed"


def test_ledger_hold_states_and_sweep_expired():
    clock = {"now": 2_000_000_000.0}   # 2033 年：晚于 2000 年的保鲜线
    ledger = BeatLedger(clock=lambda: clock["now"])
    beat = _beat("b2", valid_until="2000-01-01T00:00:00+00:00")
    ledger.record(beat)

    ledger.receive_ack(BeatAck("b2", "main", BeatAckStatus.suppressed))
    assert ledger.state_of("b2") == "held"

    expired = ledger.sweep_expired()
    assert [b.beat_id for b in expired] == ["b2"]
    assert ledger.state_of("b2") == "expired"


def test_ledger_unknown_ack_ignored():
    ledger = BeatLedger()
    ledger.receive_ack(BeatAck("ghost", "main", "performed"))   # 不抛错
    assert ledger.state_of("ghost") == ""


# ── 排程器 + 出站口 ─────────────────────────────────────────────────────────

def test_scheduler_emits_due_beats():
    bus = InProcessStoryBus()
    received: list[LifeStoryBeat] = []
    bus.bind_inbox(on_beat=received.append)

    outbox = StoryOutbox(bus.deliver_beat)
    ledger = BeatLedger()

    class _Recording:
        def emit(self, draft):
            beat = outbox.emit(draft)
            if beat is not None:
                ledger.record(beat)
            return beat

    source = CallableBeatSource(lambda now: [
        BeatDraft(narrative="第一拍", channels=("main",)),
        BeatDraft(narrative="第二拍", channels=("main",)),
    ])
    scheduler = StoryScheduler(_Recording(), source)
    result = scheduler.tick()

    assert result["emitted"] == 2
    assert len(received) == 2
    assert ledger.state_of(received[0].beat_id) == "pending"


# ── 组装运行件（wiring） ────────────────────────────────────────────────────

class _SoulStub:
    """无 _ensure_speak_service：桥接应回 suppressed 而不是抛错。"""

    def __getattr__(self, name):
        raise AttributeError(name)


def test_story_runtime_tick_end_to_end_suppressed_without_speak():
    soul = _SoulStub()
    rt = StoryRuntime(soul, source=CallableBeatSource(lambda now: [
        BeatDraft(narrative="她想说说今天的事", channels=("main",)),
    ]))

    class _LedgerSpy:
        def __init__(self, inner):
            self.inner = inner
            self.states = []

        def receive_ack(self, ack):
            self.states.append(ack.status_value())
            self.inner.receive_ack(ack)

    spy = _LedgerSpy(rt.ledger)
    rt.bus.bind_life_side(ack_receiver=spy.receive_ack, signal_inbox=lambda s: None)

    result = rt.tick()
    assert result["emitted"] == 1
    assert spy.states == [BeatAckStatus.suppressed.value]   # speak 未就绪 → 改期语义


def test_ensure_story_runtime_cached_per_soul():
    from agent.soul.wiring.story import ensure_story_runtime
    soul = _SoulStub()
    assert ensure_story_runtime(soul) is ensure_story_runtime(soul)


def test_runtime_cleans_up_with_soul():
    import gc
    from agent.soul.wiring.story import ensure_story_runtime, _runtimes
    soul = _SoulStub()
    ensure_story_runtime(soul)
    assert soul in _runtimes
    del soul
    gc.collect()
    assert len(list(_runtimes.keys())) == 0 or all(s is not None for s in _runtimes.keys())
