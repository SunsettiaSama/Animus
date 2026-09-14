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
from datetime import datetime, timezone
from typing import Any, Callable

from agent.soul.life.story import (
    BeatLedger,
    CallableBeatSource,
    StoryCardStore,
    StoryOutbox,
    StoryScheduler,
)
from agent.soul.storybus import (
    BeatAck,
    BeatAckStatus,
    BeatDraft,
    BeatProvenance,
    LifeStoryBeat,
    PerformanceHint,
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
    """speak 侧收件口：角色先决策（开口/挂起/沉默），再走表演路径。

    语义（R7）：
    - 决策经 ``BeatOpeningPolicy``（角色开口决策的确定性规则版）；
    - perform_now → enqueue_agent_outbound → performed/suppressed；
    - hold（speak 未就绪 / 用户在忙）→ suppressed（life 可改期重投）；
    - silence（角色选择沉默）→ silenced（不是失败）；
    - ProgressSync 暂不消费（前端帧扩展属 Phase 3 / 2d）。
    """

    def __init__(self, soul: Any, bus: InProcessStoryBus, *, policy=None) -> None:
        from agent.soul.speak.responders.request_driven.character.beat_policy import (
            BeatOpeningPolicy,
        )

        self._soul = weakref.ref(soul)
        self._bus = bus
        self._policy = policy or BeatOpeningPolicy()

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
            decision = self._policy.decide(beat, speak_ready=speak is not None)
            status: BeatAckStatus
            if decision.perform_now:
                status = self._perform(speak, beat, channel)
            elif decision.action == "silence":
                status = BeatAckStatus.silenced
            else:
                status = BeatAckStatus.suppressed
            logger.info(
                "[story.inbox] beat %s channel %s -> %s (%s)",
                beat.beat_id, channel, status.value, decision.reason,
            )
            self._bus.send_ack(BeatAck(beat.beat_id, channel=channel, status=status))

    def _perform(self, speak: Any, beat: LifeStoryBeat, channel: str) -> BeatAckStatus:
        if speak is None:
            return BeatAckStatus.suppressed
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
            return BeatAckStatus.performed if delivered else BeatAckStatus.suppressed
        except Exception:  # noqa: BLE001
            logger.exception("[story.inbox] enqueue failed: %s", beat.beat_id)
            return BeatAckStatus.suppressed

    def receive_progress(self, sync: StoryProgressSync) -> None:
        """进度段 → WS story_progress 帧（无在场连接时丢弃——可丢语义）。"""
        self._emit_story_frame("story_progress", {
            "card_id": sync.card_id,
            "current": sync.current,
            "upcoming": list(sync.upcoming),
            "updated_at": sync.updated_at,
        })

    def emit_card(self, card: Any) -> None:
        """卡片建立 → WS story_card 帧（大纲段 + 初始进度）。"""
        self._emit_story_frame("story_card", {
            "card_id": card.card_id,
            "outline": card.outline,
            "current": card.current,
            "upcoming": list(card.upcoming),
            "updated_at": card.updated_at,
        })

    def _emit_story_frame(self, kind: str, payload: dict) -> None:
        soul = self._soul()
        if soul is None:
            return
        try:
            port = soul.speak_outbound.stream_port
        except Exception:  # noqa: BLE001 — speak 未就绪
            return
        if port is None:
            return
        from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent

        for channel in ("main",):
            try:
                port.emit(
                    f"live:{channel}",
                    SpeakStreamEvent(kind=kind, text="", final=True, meta=dict(payload)),
                )
            except Exception:  # noqa: BLE001 — 帧失败不反噬剧情
                logger.exception("[story.inbox] frame emit failed: %s", kind)


class StoryRuntime:
    """life 侧剧情运行件组合：总线 + 出站口 + 账本 + 排程器。"""

    def __init__(self, soul: Any, *, source: CallableBeatSource | None = None, policy=None) -> None:
        from collections import deque

        from agent.soul.speak.responders.request_driven.character.beat_policy import (
            BeatOpeningPolicy,
        )

        self.bus = InProcessStoryBus()
        self.ledger = BeatLedger(on_advance=self._on_advance)
        self.outbox = StoryOutbox(self.bus.deliver_beat)
        self.cards = StoryCardStore(self.bus.sync_progress)
        self._recorder = self._recording_outbox()
        self.scheduler = StoryScheduler(
            self._recorder, source or CallableBeatSource()
        )
        self.bus.bind_life_side(
            ack_receiver=self.ledger.receive_ack,
            signal_inbox=self._receive_signal,
        )
        self._soul = weakref.ref(soul)
        self._inbox_bound = False
        self._policy = policy or BeatOpeningPolicy()
        self._recent_signals = deque(maxlen=20)
        self._director_dirty = False

    def _recording_outbox(self):
        """包装 outbox：先记账后投递——同步回执（suppressed 等）才能落到账上。"""
        outer = self

        class _Recording:
            def emit(self, draft):
                beat = outer.outbox.build(draft)
                if beat is None:
                    return None
                outer.ledger.record(beat)
                if not outer.outbox.deliver(beat):
                    return None
                return beat

        return _Recording()

    def emit_drafts(self, drafts) -> int:
        """剧情事件直发口（landmark/surprise 等即时剧情入口）。"""
        self.ensure_inbox()
        emitted = 0
        for draft in drafts:
            if self._recorder.emit(draft) is not None:
                emitted += 1
        return emitted

    def ensure_inbox(self) -> None:
        """speak 收件桥懒绑定（speak 服务可能晚于剧情运行件就绪）。"""
        if self._inbox_bound:
            return
        soul = self._soul()
        if soul is None:
            return
        self._bridge = SpeakBeatInboxBridge(soul, self.bus, policy=self._policy)
        self.bus.bind_inbox(
            on_beat=self._bridge.receive_beat,
            on_progress=self._bridge.receive_progress,
        )
        self._inbox_bound = True

    def open_card(self, outline: str, *, card_id: str | None = None):
        """开卡 + 下发 story_card 帧（大纲段冻结，进度段从空开始）。"""
        self.ensure_inbox()
        card = self.cards.open(outline, card_id=card_id)
        bridge = getattr(self, "_bridge", None)
        if bridge is not None:
            bridge.emit_card(card)
        return card

    def advance_card(self, card_id: str, *, current: str, upcoming=()):
        """推进进度段：StoryProgressSync → bus → story_progress 帧。"""
        self.ensure_inbox()
        return self.cards.advance(card_id, current=current, upcoming=upcoming)

    def tick(self) -> dict:
        self.ensure_inbox()
        result = self.scheduler.tick()
        expired = self.ledger.sweep_expired()
        if expired:
            result["expired_archived"] = len(expired)
        return result

    def _receive_signal(self, signal: StorySignal) -> None:
        """用户轮信号 → 导演侧消费（2c）：
        - 环形留存近期信号（导演重估的输入）；
        - 高显著度（>=0.7）置失效标志——预跑缓存/剧情走向需重估（R9）。"""
        self._recent_signals.append(signal)
        if self._policy.salience_warrants_rewrite(signal.salience_hint):
            self._director_dirty = True
            logger.info(
                "[story.runtime] high-salience signal (%.2f) → director dirty",
                signal.salience_hint,
            )

    @property
    def director_dirty(self) -> bool:
        """剧情走向可能已被用户显著改变（导演应重估；读后清除）。"""
        return self._director_dirty

    def clear_director_dirty(self) -> None:
        self._director_dirty = False

    @property
    def recent_signals(self) -> tuple[StorySignal, ...]:
        return tuple(self._recent_signals)

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


# ── landmark → beat 桥（R6.2 剧情驱动的第一供給源） ─────────────────────────
# 默认投递渠道与保鲜期（需求开放问题 7/8 的默认值）；渠道配置化属 2c。

_DEFAULT_CHANNELS = ("main",)
_FRESH_SEC = 6 * 3600


def _default_hint(share_desire: float = 0.5) -> PerformanceHint:
    return PerformanceHint(
        urgency="normal",
        share_desire=share_desire,
        valid_until=datetime.fromtimestamp(time.time() + _FRESH_SEC, tz=timezone.utc).isoformat(),
    )


def beats_from_landmark_fills(fills: list[dict]) -> list[BeatDraft]:
    """landmark 触发填补项（life.api.fill_due_landmarks 的返回）→ beat 草稿。"""
    drafts: list[BeatDraft] = []
    for item in fills:
        narrative = str(item.get("hint") or item.get("narrative") or "").strip()
        if not narrative:
            continue
        drafts.append(BeatDraft(
            narrative=narrative,
            channels=_DEFAULT_CHANNELS,
            kind="landmark_progress",
            hint=_default_hint(share_desire=float(item.get("salience", 0.6))),
            provenance=BeatProvenance(
                landmark_id=str(item.get("landmark_id") or item.get("landmark_agenda_id") or ""),
                agenda_id=str(item.get("landmark_agenda_id") or ""),
            ),
        ))
    return drafts


def beat_from_subjective_event(event: dict, *, source_tick: str = "") -> BeatDraft | None:
    """plan_landmark 的主观事件（subjective_event.hint）→ beat 草稿。"""
    narrative = str(event.get("hint") or "").strip()
    if not narrative:
        return None
    return BeatDraft(
        narrative=narrative,
        channels=_DEFAULT_CHANNELS,
        kind="landmark_progress",
        hint=_default_hint(share_desire=0.6),
        provenance=BeatProvenance(source_tick=source_tick),
    )


def beat_from_surprise(detail: dict) -> BeatDraft | None:
    """surprise tick（life 惊奇事件）→ beat 草稿。"""
    if not detail.get("triggered"):
        return None
    narrative = str(detail.get("narrative") or "").strip()
    if not narrative:
        return None
    return BeatDraft(
        narrative=narrative,
        channels=_DEFAULT_CHANNELS,
        kind="incident",
        hint=_default_hint(share_desire=min(0.95, 0.5 + float(detail.get("salience", 0.5)) * 0.4)),
    )


def emit_story_beats(soul: Any, drafts: list[BeatDraft]) -> int:
    """统一剧情发射口（orchestrator 的 landmark/surprise 处理器调用）。"""
    if not drafts:
        return 0
    return ensure_story_runtime(soul).emit_drafts(drafts)


def send_story_signal(
    soul: Any,
    *,
    session_id: str,
    turn_digest: str,
    salience_hint: float = 0.3,
) -> None:
    """用户轮信号（speak → life）：导演侧做剧情重估/缓存失效判定（R9）。

    挂在轮末记账之后（soul_dialogue.record_pending_turn）；soul 缺席时静默跳过。
    """
    if soul is None:
        return
    from agent.soul.memory.timeline import channel_of

    digest = str(turn_digest or "").strip()[:120]
    if not digest:
        return
    ensure_story_runtime(soul).bus.send_signal(StorySignal(
        session_id=str(session_id or ""),
        channel=channel_of(session_id),
        turn_digest=digest,
        salience_hint=float(salience_hint),
    ))
