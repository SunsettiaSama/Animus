"""speak/performance 旁路表演管线契约（v7 批次）。

BeatPerformer 是 speak 侧唯一的剧情表演通路：决策（policy）× 帧闸（gate）
× 表演端口（perform）× 回执口（send_ack）全部经构造注入，与总线/speak
服务零耦合——本文件用 fake 端口锁定管线语义。
"""
from __future__ import annotations

from agent.soul.speak.performance import BeatPerformer
from agent.soul.speak.performance.policy import BeatOpeningPolicy, FrameGate
from agent.soul.storybus import BeatAckStatus, LifeStoryBeat, PerformanceHint


def _beat(beat_id="b1", urgency="normal", desire=0.8, channels=("main",)):
    return LifeStoryBeat(
        beat_id=beat_id,
        narrative="n",
        channels=channels,
        hint=PerformanceHint(urgency=urgency, share_desire=desire),
    )


class _Harness:
    """fake 端口装配：记录演出与回执，speak 就绪度可切换。"""

    def __init__(self, *, speak_ready=True, policy: BeatOpeningPolicy | None = None,
                 gate: FrameGate | None = None):
        self.speak = object() if speak_ready else None
        self.performed: list[tuple[str, str]] = []
        self.acks = []
        self.p = BeatPerformer(
            speak_provider=lambda: self.speak,
            perform=self._perform,
            send_ack=self._ack,
            policy=policy,
            gate=gate,
        )

    def _perform(self, speak, beat, channel):
        self.performed.append((beat.beat_id, channel))
        return BeatAckStatus.performed

    def _ack(self, ack):
        self.acks.append(ack)


def test_perform_ready_and_eager_opens():
    h = _Harness()
    outcomes = h.p.receive_beat(_beat(desire=0.9))
    assert outcomes[0][0] == "main"
    assert outcomes[0][1] is BeatAckStatus.performed
    assert h.performed == [("b1", "main")]
    assert h.acks[0].status is BeatAckStatus.performed
    assert h.acks[0].channel == "main"


def test_hold_when_speak_not_ready():
    h = _Harness(speak_ready=False)
    outcomes = h.p.receive_beat(_beat())
    assert outcomes[0][1] is BeatAckStatus.suppressed
    assert not h.performed
    assert h.acks[0].status is BeatAckStatus.suppressed


def test_frame_gate_suppresses_same_frame_then_recovers():
    clock = {"t": 1000.0}
    gate = FrameGate(window_sec=5.0, clock=lambda: clock["t"])
    h = _Harness(gate=gate)
    o1 = h.p.receive_beat(_beat(beat_id="b1", desire=0.9))
    o2 = h.p.receive_beat(_beat(beat_id="b2", desire=0.9))
    assert o1[0][1] is BeatAckStatus.performed
    assert o2[0][1] is BeatAckStatus.suppressed      # 帧内裁决，不留悬案
    assert len(h.performed) == 1
    clock["t"] += 6.0
    o3 = h.p.receive_beat(_beat(beat_id="b3", desire=0.9))
    assert o3[0][1] is BeatAckStatus.performed        # 下一帧恢复


def test_silence_path_for_calm_low_desire():
    h = _Harness()
    outcomes = h.p.receive_beat(_beat(urgency="calm", desire=0.1))
    assert outcomes[0][1] is BeatAckStatus.silenced
    assert not h.performed
    assert h.acks[0].status is BeatAckStatus.silenced


def test_multi_channel_independent_opening_and_acks():
    h = _Harness()
    outcomes = h.p.receive_beat(_beat(channels=("c1", "c2")))
    assert [status for _, status, _ in outcomes] == [
        BeatAckStatus.performed,
        BeatAckStatus.performed,
    ]
    assert set(h.performed) == {("b1", "c1"), ("b1", "c2")}
    assert [ack.channel for ack in h.acks] == ["c1", "c2"]
