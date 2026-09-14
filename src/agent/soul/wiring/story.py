"""wiring.story — storybus 进程内总线 + life/speak 剧情接线（L3 组装层）。

职责边界：
- ``InProcessStoryBus``：四类消息的进程内路由（幂等、保鲜检查、异常隔离）；
- ``SpeakBeatInboxBridge``：speak 侧收件口的**过渡桥**——beat 经现有
  ``enqueue_agent_outbound`` 主动路径演出；开口时机收拢进角色（R7/2c）后，
  本桥退位为 BeatPerformer 的投递适配；
- ``StoryRuntime``：life 侧运行件（outbox + 账本 + 排程器）的组合根；
  ``ensure_story_runtime(soul)`` 以 WeakKeyDictionary 缓存，SoulService 零改动。
"""
from __future__ import annotations

import logging
import threading
import time
import weakref
from typing import Any, Callable

from agent.soul.life.story import BeatLedger, CallableBeatSource, StoryOutbox, StoryScheduler
from agent.soul.storybus import (
    BeatAck,
    BeatAckStatus,
    LifeStoryBeat,
    StoryProgressSync,
    StorySignal,
)

logger = logging.getLogger(__name__)


class InProcessStoryBus:
    """进程内剧情总线：life 出站 ↔ speak 收件 ↔ 回执/信号回流。

    语义（协议 §7.3）：
    - beat 按 beat_id 幂等（重复投递拒收）；
    - 过期 beat 不转发，直接回 ack(expired)（归档语义由 life 账本承接）；
    - 进度消息无 ack、可丢弃；接收方异常被隔离，不影响另一侧。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen_beats: set[str] = set()
        self._inbox_beat: Callable[[LifeStoryBeat], None] | None = None
        self._inbox_progress: Callable[[StoryProgressSync], None] | None = None
        self._ack_receiver: Callable[[BeatAck], None] | None = None
        self._signal_inbox: Callable[[StorySignal], None] | None = None

    # ── 装配（wiring 调用） ────────────────────────────────────────────────
    def bind_inbox(self, *, on_beat: Callable[[LifeStoryBeat], None] | None = None,
                   on_progress: Callable[[StoryProgressSync], None] | None = None) -> None:
        with self._lock:
            if on_beat is not None:
                self._inbox_beat = on_beat
            if on_progress is not None:
                self._inbox_progress = on_progress

    def bind_life_side(self, *, ack_receiver: Callable[[BeatAck], None] | None = None,
                       signal_inbox: Callable[[StorySignal], None] | None = None) -> None:
        with self._lock:
            if ack_receiver is not None:
                self._ack_receiver = ack_receiver
            if signal_inbox is not None:
                self._signal_inbox = signal_inbox

    # ── life 侧入口（实现 LifeStoryOutboxPort） ───────────────────────────
    def deliver_beat(self, beat: LifeStoryBeat) -> bool:
        with self._lock:
            if beat.beat_id in self._seen_beats:
                return False
            self._seen_beats.add(beat.beat_id)
            inbox = self._inbox_beat
        if beat.is_expired():
            self.send_ack(BeatAck(beat.beat_id, channel=str(beat.channels[0]) if beat.channels else "",
                                  status=BeatAckStatus.expired))
            return False
        if inbox is None:
            return False
        try:
            inbox(beat)
        except Exception:  # noqa: BLE001 — speak 侧故障不反噬 life
            logger.exception("[storybus] inbox beat handler failed: %s", beat.beat_id)
            return False
        return True

    def sync_progress(self, sync: StoryProgressSync) -> None:
        with self._lock:
            inbox = self._inbox_progress
        if inbox is None:
            return
        try:
            inbox(sync)
        except Exception:  # noqa: BLE001
            logger.exception("[storybus] progress handler failed: %s", sync.card_id)

    # ── speak 侧入口 ──────────────────────────────────────────────────────
    def send_ack(self, ack: BeatAck) -> None:
        with self._lock:
            receiver = self._ack_receiver
        if receiver is None:
            return
        try:
            receiver(ack)
        except Exception:  # noqa: BLE001
            logger.exception("[storybus] ack receiver failed: %s", ack.beat_id)

    def send_signal(self, signal: StorySignal) -> None:
        with self._lock:
            inbox = self._signal_inbox
        if inbox is None:
            return
        try:
            inbox(signal)
        except Exception:  # noqa: BLE001
            logger.exception("[storybus] signal inbox failed: %s", signal.session_id)


class SpeakBeatInboxBridge:
    """过渡桥：beat → 现有主动出站路径（enqueue_agent_outbound）。

    过渡语义（2c 角色收拢前的诚实标注）：
    - 投递成功即回 performed（演出确认细化到 delivery/ack 链路属 2c）；
    - speak 未就绪 / 投递失败回 suppressed（life 可改期）；
    - ProgressSync 暂不消费（前端帧扩展属 Phase 3 / 2d）。
    """

    def __init__(self, soul: Any, bus: InProcessStoryBus) -> None:
        self._soul = weakref.ref(soul)
        self._bus = bus

    def _speak(self):
        soul = self._soul()
        if soul is None:
            return None
        try:
            svc = soul._ensure_speak_service()
        except Exception:  # noqa: BLE001 — speak 尚未就绪属正常冷启动
            return None
        return svc

    def receive_beat(self, beat: LifeStoryBeat) -> None:
        speak = self._speak()
        channels = beat.channels or ("main",)
        for channel in channels:
            status = BeatAckStatus.suppressed
            if speak is not None:
                payload = {
                    "session_id": f"live:{channel}",
                    "channel_id": channel,
                    "message": beat.narrative,
                    "source": "story",
                    "agent_initiated": True,
                    "wait_reply": False,
                    "task_name": "剧情推进",
                    "create_window": True,
                    "beat_id": beat.beat_id,
                    "card_id": beat.card_id,
                }
                try:
                    result = speak.enqueue_agent_outbound(payload)
                    delivered = bool(result.get("delivered") or result.get("ok"))
                    status = BeatAckStatus.performed if delivered else BeatAckStatus.suppressed
                except Exception:  # noqa: BLE001
                    logger.exception("[story.inbox] enqueue failed: %s", beat.beat_id)
            self._bus.send_ack(BeatAck(beat.beat_id, channel=channel, status=status))

    def receive_progress(self, sync: StoryProgressSync) -> None:
        logger.debug("[story.inbox] progress (Phase 2d/3 接前端帧): %s", sync.card_id)


class StoryRuntime:
    """life 侧剧情运行件组合：总线 + 出站口 + 账本 + 排程器。"""

    def __init__(self, soul: Any, *, source: CallableBeatSource | None = None) -> None:
        self.bus = InProcessStoryBus()
        self.ledger = BeatLedger(on_advance=self._on_advance)
        self.outbox = StoryOutbox(self.bus.deliver_beat)
        self.scheduler = StoryScheduler(
            self._recording_outbox(), source or CallableBeatSource()
        )
        self.bus.bind_life_side(
            ack_receiver=self.ledger.receive_ack,
            signal_inbox=self._receive_signal,
        )
        self._soul = weakref.ref(soul)
        self._inbox_bound = False

    def _recording_outbox(self):
        """包装 outbox：投递成功的 beat 同时记入账本待回执。"""
        outer = self

        class _Recording:
            def emit(self, draft):
                beat = outer.outbox.emit(draft)
                if beat is not None:
                    outer.ledger.record(beat)
                return beat

        return _Recording()

    def ensure_inbox(self) -> None:
        """speak 收件桥懒绑定（speak 服务可能晚于剧情运行件就绪）。"""
        if self._inbox_bound:
            return
        soul = self._soul()
        if soul is None:
            return
        bridge = SpeakBeatInboxBridge(soul, self.bus)
        self.bus.bind_inbox(on_beat=bridge.receive_beat, on_progress=bridge.receive_progress)
        self._inbox_bound = True

    def tick(self) -> dict:
        self.ensure_inbox()
        result = self.scheduler.tick()
        expired = self.ledger.sweep_expired()
        if expired:
            result["expired_archived"] = len(expired)
        return result

    def _receive_signal(self, signal: StorySignal) -> None:
        # 2c/2d：导演在此做缓存失效判定（R9）；现阶段仅记账
        logger.debug("[story.runtime] signal %s salience=%.2f", signal.channel, signal.salience_hint)

    def _on_advance(self, beat: LifeStoryBeat, status: BeatAckStatus) -> None:
        # 2b 完整版：performed → 推进 landmark/chronicle；expired → 归档"错过的剧情"
        logger.info("[story.runtime] beat %s -> %s", beat.beat_id, status.value)


_runtimes: "weakref.WeakKeyDictionary[Any, StoryRuntime]" = weakref.WeakKeyDictionary()
_runtimes_lock = threading.Lock()


def ensure_story_runtime(soul: Any) -> StoryRuntime:
    """按 soul 实例缓存剧情运行件；SoulService 零改动（组装在 wiring 层）。"""
    with _runtimes_lock:
        rt = _runtimes.get(soul)
        if rt is None:
            rt = StoryRuntime(soul)
            _runtimes[soul] = rt
        return rt
