"""performance.performer — 旁路表演管线（storybus beat → 角色决策 → 表演 → 回执）。

新设计过程下 speak 侧唯一的剧情表演通路：

    beat 到达 → BeatOpeningPolicy 三择一（hint 建议 × 在场）→
    FrameGate 时间帧单开口裁决 → perform 端口演出 → 逐渠道 ack 回 life

speak 内的旧"决定说什么"机器（directors / screenwriter / story_pool /
orchestrator 主动循环的剧情供能）**不在本管线上**——本管线只消费 life
已经决定好的内容，开口时机由角色自决（R7）。管线与总线零耦合：决策
所需的一切经构造注入（speak 解析器、表演端口、回执发送口），可整体
fake 测试。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from agent.soul.storybus import BeatAck, BeatAckStatus, LifeStoryBeat

from .policy import (
    PERFORM_NOW,
    BeatOpeningPolicy,
    FrameGate,
    OpeningDecision,
)

logger = logging.getLogger(__name__)


class BeatPerformer:
    """旁路管线引擎：开口决策与表演收拢于此（wiring 桥退位为投递适配）。"""

    def __init__(
        self,
        *,
        speak_provider: Callable[[], Any | None],
        perform: Callable[[Any, LifeStoryBeat, str], BeatAckStatus],
        send_ack: Callable[[BeatAck], None],
        policy: BeatOpeningPolicy | None = None,
        gate: FrameGate | None = None,
    ) -> None:
        self._speak_provider = speak_provider
        self._perform = perform
        self._send_ack = send_ack
        self._policy = policy or BeatOpeningPolicy()
        self._gate = gate or FrameGate()

    def _safe_speak(self) -> Any | None:
        try:
            return self._speak_provider()
        except Exception:  # noqa: BLE001 — speak 尚未就绪属正常冷启动
            return None

    @staticmethod
    def _gate_open(speak: Any) -> bool:
        """life→speak 握手门（v7）：先确认再通信。

        宿主声明 ``story_gate_open``（激活会话 + 未睡眠）才进入开口决策；
        无门宿主（测试/旧宿主）默认放行。
        """
        gate = getattr(speak, "story_gate_open", None)
        if gate is None:
            return True
        try:
            return bool(gate())
        except Exception:  # noqa: BLE001 — 门态不可得视为关门
            return False

    def receive_beat(self, beat: LifeStoryBeat) -> list[tuple[str, BeatAckStatus, str]]:
        """逐渠道裁决并演出；返回 (channel, status, reason) 供账本与日志。"""
        speak = self._safe_speak()
        # 握手门关闭（无激活会话/睡眠）→ hold：不等待，life 账本挂起改期
        speak_ready = speak is not None and self._gate_open(speak)
        channels = beat.channels or ("main",)
        outcomes: list[tuple[str, BeatAckStatus, str]] = []
        for channel in channels:
            decision = self._policy.decide(beat, speak_ready=speak_ready)
            status: BeatAckStatus
            if decision.perform_now and not self._gate.try_open(channel):
                # 时间帧单开口约定：本帧已开口 → 帧内裁决为改期（不留悬案）
                status = BeatAckStatus.suppressed
                decision = OpeningDecision("hold", "frame_busy")
            elif decision.perform_now:
                status = self._perform(speak, beat, channel)
            elif decision.action == "silence":
                status = BeatAckStatus.silenced
            else:
                status = BeatAckStatus.suppressed
            logger.info(
                "[performance] beat %s channel %s -> %s (%s)",
                beat.beat_id, channel, status.value, decision.reason,
            )
            self._send_ack(BeatAck(beat.beat_id, channel=channel, status=status))
            outcomes.append((channel, status, decision.reason))
        return outcomes
