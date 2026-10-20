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
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from agent.soul.life.story import (
    BeatLedger,
    CallableBeatSource,
    EvolutionPool,
    LandmarkScreenwriter,
    PoolEntry,
    StoryCardStore,
    StoryOutbox,
    StoryScheduler,
)
from agent.soul.life.story.writer import hhmm
from agent.soul.life.virtual.narrative.engine import looks_like_artifact
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
    """speak 侧收件口：旁路表演管线（performance.BeatPerformer）的投递适配。

    开口决策、时间帧单开口闸与表演已收拢进 speak/performance 管线（R7）；
    本桥只负责解析 speak 服务、提供表演端口（enqueue_agent_outbound →
    outbound bus，纯运输不涉旧剧情机器）与 ProgressSync/卡片帧下发。
    """

    def __init__(self, soul: Any, bus: InProcessStoryBus, *, policy=None, frame_gate=None) -> None:
        from agent.soul.speak.performance import BeatPerformer

        self._soul = weakref.ref(soul)
        self._bus = bus
        self._performer = BeatPerformer(
            speak_provider=self._speak,
            perform=self._perform,
            send_ack=bus.send_ack,
            policy=policy,
            gate=frame_gate,
        )

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
        self._performer.receive_beat(beat)

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
    """life 侧剧情运行件组合：总线 + 出站口 + 账本 + 排程器 + 演化预跑。"""

    def __init__(
        self,
        soul: Any,
        *,
        source: CallableBeatSource | None = None,
        policy=None,
        journal: Any | None = None,
    ) -> None:
        from collections import deque

        from agent.soul.speak.performance.policy import (
            BeatOpeningPolicy,
            FrameGate,
        )

        self.bus = InProcessStoryBus()
        self.ledger = BeatLedger(on_advance=self._on_advance)
        self.outbox = StoryOutbox(self.bus.deliver_beat)
        self.cards = StoryCardStore(self.bus.sync_progress)
        if journal is None:
            from agent.soul.memory.timeline import default_journal

            journal = default_journal()
        self._journal = journal
        self.pool = EvolutionPool()
        self.writer = LandmarkScreenwriter()
        self._recorder = self._recording_outbox()
        self.scheduler = StoryScheduler(
            self._recorder,
            source or CallableBeatSource(self._due_pool_beats),
        )
        self.bus.bind_life_side(
            ack_receiver=self.ledger.receive_ack,
            signal_inbox=self._receive_signal,
        )
        self._soul = weakref.ref(soul)
        self._inbox_bound = False
        self._policy = policy or BeatOpeningPolicy()
        self._gate = FrameGate()
        self._recent_signals = deque(maxlen=20)
        self._director_dirty = False
        self._evolve_inflight = False
        self._intent_sent: set[str] = set()  # 已落 intent 的地标/beat 去重

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
        self._bridge = SpeakBeatInboxBridge(
            soul, self.bus, policy=self._policy, frame_gate=self._gate
        )
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
        result: dict[str, Any] = {}
        # 导演失效重估（R9）：用户轮高显著信号后，未投递的预跑稿整池重算——
        # 下一拍演化过场会从手账 narrative 零成本重出稿（echo 路径）。
        if self._director_dirty:
            dropped = self.pool.drop_pending()
            self.clear_director_dirty()
            if dropped:
                result["invalidated"] = dropped
        # 预约改期（R7.2）：只重投"本拍之前"已挂起的 beat——同拍内刚被抑制的
        # 留到下一拍，避免自追自尾；直接调用 redeliver_held() 不受此限。
        pre_held = {b.beat_id for b in self.ledger.held()}
        result.update(self.scheduler.tick())
        result["redelivered"] = self.redeliver_held(only_ids=pre_held)
        expired = self.ledger.sweep_expired()
        if expired:
            result["expired_archived"] = len(expired)
        result["pool_depth"] = len(self.pool.pending_landmark_ids())
        return result

    # ── 预约轴提前演化（导演规划生活 + 编剧成稿 + 预跑池，R9 预约轴版） ──

    def _due_pool_beats(self, now: float) -> list:
        """StoryScheduler 的供给源：预跑池到点出货（零 LLM 等待）。"""
        return [e.draft for e in self.pool.pop_due(now)]

    def maybe_submit_evolve(self, orchestrator) -> bool:
        """有容量时把演化过道作为一次性重任务提交给心跳 worker。

        固定 id ``story-evolve`` 借 worker pending 去重防重入；
        演化本体见 :meth:`evolve_pass`。
        """
        if orchestrator is None:
            return False
        if self._evolve_inflight or not self.pool.has_capacity():
            return False
        if self._soul() is None:
            return False
        from agent.soul.heartbeat.schedule.item import ChecklistItem

        return orchestrator.submit_heavy(ChecklistItem(
            id="story-evolve",
            domain="story",
            action="story.evolve",
            target="agent.soul.wiring.story_tick:story_evolve_entry",
            heavy=True,
        ))

    def evolve_pass(self) -> None:
        """演化过道：①窗口内预约地标提前 fill（重 LLM）；②已演化未
        开口地标的 echo 补稿（重启丢池/失效重估/到点路径先填后漏，零 LLM）。
        由心跳 SoulEvolutionWorker 执行（submit_heavy 提交）。"""
        self._evolve_inflight = True
        try:
            soul = self._soul()
            if soul is None:
                return
            try:
                api = soul.life.api
            except Exception:  # noqa: BLE001 — life 未就绪属正常冷启动
                return
            try:
                fills = api.evolve_upcoming_landmarks(within_sec=_EVOLVE_WINDOW_SEC)
            except Exception:  # noqa: BLE001
                logger.exception("[story.evolution] landmark evolve failed")
                fills = []
            for fill in fills or []:
                self._absorb(fill)
            try:
                tellable = api.done_landmarks_for_tell() or []
            except Exception:  # noqa: BLE001
                logger.exception("[story.evolution] tellable scan failed")
                tellable = []
            told = self._told_landmark_ids()
            for lm in tellable:
                lid = str(lm.get("landmark_id") or "").strip()
                if not lid or self.pool.has(lid) or lid in told:
                    continue
                draft = self.writer.write_landmark_echo(lm)
                if draft is not None:
                    self._absorb(draft, meta=lm)
        finally:
            self._evolve_inflight = False

    def _absorb(self, draft_or_fill: Any, *, meta: dict | None = None) -> bool:
        """演化材料 → 开卡 → 预跑池入池 → 卡片预告同步。"""
        if isinstance(draft_or_fill, dict) and meta is None:
            meta = draft_or_fill
            draft = self.writer.write_landmark_beat(
                draft_or_fill,
                prev=self._recent_story_context(
                    exclude_landmark=str(meta.get("landmark_id") or "")
                ),
            )
        else:
            draft = draft_or_fill
        if draft is None:
            return False
        meta = meta or {}
        lid = str(meta.get("landmark_id") or "").strip()
        if not lid or self.pool.has(lid) or lid in self._told_landmark_ids():
            # 已演出过的地标不再开口（确定性 id 之外的语义防线）
            return False
        if not draft.channels:
            draft = replace(draft, channels=_DEFAULT_CHANNELS)
        card = self.open_card(self.writer.outline_for(meta))
        draft = replace(draft, card_id=card.card_id)
        scheduled_at = str(meta.get("scheduled_at") or "")
        deliver_at = _scheduled_epoch(scheduled_at, fallback=time.time())
        ok = self.pool.put(PoolEntry(
            draft=draft,
            landmark_id=lid,
            card_id=card.card_id,
            deliver_at=deliver_at,
            intention=str(meta.get("intention") or ""),
            scheduled_at=scheduled_at,
            evolved_at=time.time(),
        ))
        if ok:
            logger.info(
                "[story.evolution] pooled landmark %s deliver_at=%s cached=True",
                lid, scheduled_at or "-",
            )
            self._sync_card_upcoming(card.card_id)
        return ok

    def _sync_card_upcoming(self, card_id: str) -> None:
        """进度段预告：当前=待演绎；upcoming=池内同卡未到点的后续稿。"""
        card = self.cards.get(card_id)
        now = time.time()
        upcoming = [
            f"「{hhmm(e.scheduled_at)}」{e.intention}".strip()
            for e in self.pool.future_by_card(card_id, now)
        ]
        current = card.current if (card and card.current) else "已排入日程，到点开演"
        try:
            self.advance_card(card_id, current=current, upcoming=upcoming)
        except Exception:  # noqa: BLE001 — 帧失败不反噬剧情
            logger.exception("[story.evolution] card sync failed: %s", card_id)

    def _recent_story_context(self, *, exclude_landmark: str = "") -> list[dict]:
        """前情：最近 3 条已演出的 story 事件（编剧串联用）。

        ``exclude_landmark``：正在写作的地标自身不进前情（避免自我串联）。
        """
        try:
            entries = self._journal.read("main", limit=200) or []
        except Exception:  # noqa: BLE001 — 流水缺失不阻塞演化
            return []
        story = [
            e for e in entries
            if str(e.get("kind")) == "story"
            and str(e.get("landmark_id") or "") != exclude_landmark
        ]
        return story[:3]  # read() 新在前

    def _told_landmark_ids(self) -> set[str]:
        try:
            entries = self._journal.read("main", limit=200) or []
        except Exception:  # noqa: BLE001
            return set()
        return {
            str(e.get("landmark_id"))
            for e in entries
            if str(e.get("kind")) == "story" and e.get("landmark_id")
        }

    def redeliver_held(self, only_ids: set[str] | None = None) -> int:
        """改期重投 held beat：speak 未就绪/帧忙/用户忙 suppressed、silenced 的
        剧情在下一拍重新起搏（保鲜期外自然过期归档，不会无限重投）。"""
        self.ensure_inbox()
        moved = 0
        for beat in list(self.ledger.held()):
            if only_ids is not None and beat.beat_id not in only_ids:
                continue
            if beat.is_expired():
                continue
            self.ledger.retire(beat.beat_id, BeatAckStatus.declined)
            draft = BeatDraft(
                narrative=beat.narrative,
                channels=beat.channels,
                card_id=beat.card_id,
                kind=beat.kind,
                hint=beat.hint,
                provenance=beat.provenance,
                cached=beat.cached,
            )
            if self._recorder.emit(draft) is not None:
                moved += 1
        return moved

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
        """账本终态推进：performed → 落时间轴流水（R5 provenance 补账）+
        卡片进度前进（R8 一致性约定：演过才推进）；suppressed/silenced →
        剧情意向不置顶（落 intent 流水并刷新上下文，告知"她打算开始做什么"）。"""
        logger.info("[story.runtime] beat %s -> %s", beat.beat_id, status.value)
        if status is BeatAckStatus.performed:
            self._record_story_performed(beat)
        elif status in (BeatAckStatus.suppressed, BeatAckStatus.silenced):
            self._record_story_intent(beat)

    def _record_story_performed(self, beat: LifeStoryBeat) -> None:
        channel = beat.channels[0] if beat.channels else "main"
        try:
            self._journal.append_event(
                session_id=f"live:{channel}",
                text=beat.narrative,
                kind="story",
                beat_id=beat.beat_id,
                card_id=beat.card_id,
                landmark_id=beat.provenance.landmark_id,
                occurred_at=beat.provenance.source_tick,
                salience=float(beat.hint.share_desire),
            )
        except Exception:  # noqa: BLE001 — 流水是读模型，写失败不打断
            logger.exception("[story.runtime] story event append failed")
        if beat.card_id:
            try:
                upcoming = [
                    f"「{hhmm(e.scheduled_at)}」{e.intention}".strip()
                    for e in self.pool.future_by_card(beat.card_id, time.time())
                ]
                self.advance_card(
                    beat.card_id, current=beat.narrative, upcoming=upcoming
                )
            except Exception:  # noqa: BLE001
                logger.exception("[story.runtime] card advance failed")

    def _record_story_intent(self, beat: LifeStoryBeat) -> None:
        """剧情意向（不置顶）：beat 暂不开口 → intent 落流水 + 刷新上下文。

        不打断当前对话、卡片不置顶——只是让角色"知道她打算开始做什么"，
        开口时机仍由角色自决（R7）。按 landmark（无则 beat_id）去重，
        改期重投不重复记。
        """
        key = beat.provenance.landmark_id or beat.beat_id
        if key in self._intent_sent:
            return
        self._intent_sent.add(key)
        channel = beat.channels[0] if beat.channels else "main"
        brief = beat.narrative.strip()
        if len(brief) > 60:
            brief = brief[:60] + "…"
        try:
            self._journal.append_event(
                session_id=f"live:{channel}",
                text=f"她打算开始：{brief}",
                kind="story_intent",
                beat_id=beat.beat_id,
                card_id=beat.card_id,
                landmark_id=beat.provenance.landmark_id,
                occurred_at=beat.provenance.source_tick,
                salience=float(beat.hint.share_desire),
            )
        except Exception:  # noqa: BLE001 — 流水写失败不打断
            logger.exception("[story.runtime] story intent append failed")
        self._refresh_speak_window(channel)

    def _refresh_speak_window(self, channel: str) -> None:
        """唤醒中的 speak：立刻刷新时间轴窗口（睡眠时不刷，进房自然带上）。"""
        soul = self._soul()
        if soul is None:
            return
        try:
            speak = soul._ensure_speak_service()
            if speak is not None and speak.story_gate_open():
                speak.inject_timeline_window(f"live:{channel}")
        except Exception:  # noqa: BLE001 — 刷新失败不影响剧情链
            pass


_runtimes: "weakref.WeakKeyDictionary[Any, StoryRuntime]" = weakref.WeakKeyDictionary()
_runtimes_lock = threading.Lock()


class _MemoryTimelineJournal:
    """测试桩专用内存时间轴：只保数据不落盘，read 语义与 TurnJournal 对齐。

    背景：ensure_story_runtime 此前对桩 soul 也落到全局 default_journal()
    （真实 .react 时间轴），storybus 测试夹具（"第一拍""预约的内容"等）
    曾因此污染 webui 回忆面板。
    """

    def __init__(self) -> None:
        self._entries: list[dict] = []

    def append_event(self, *, session_id: str, text: str, kind: str, **kwargs) -> None:
        _ = session_id
        self._entries.append({"text": text, "kind": kind, **kwargs})

    def append_turn(self, *args, **kwargs) -> None:  # 兼容 TurnJournal 接口
        _ = args, kwargs

    def read(self, channel: str, *, limit: int = 50, before: str = "") -> list[dict]:
        _ = channel, before
        entries = [dict(e, at="") for e in self._entries]
        return entries[-limit:][::-1]


def _journal_for_soul(soul: Any):
    """生产 SoulService 共享全局时间轴；其余（测试桩/演示 stub）用内存隔离。"""
    if type(soul).__name__ == "SoulService":
        from agent.soul.memory.timeline import default_journal

        return default_journal()
    return _MemoryTimelineJournal()


def ensure_story_runtime(soul: Any) -> StoryRuntime:
    """按 soul 实例缓存剧情运行件；SoulService 零改动（组装在 wiring 层）。"""
    with _runtimes_lock:
        rt = _runtimes.get(soul)
        if rt is None:
            rt = StoryRuntime(soul, journal=_journal_for_soul(soul))
            _runtimes[soul] = rt
        return rt


# ── landmark → beat 桥（R6.2 剧情驱动的第一供給源） ─────────────────────────
# 默认投递渠道与保鲜期（需求开放问题 7/8 的默认值）；渠道配置化属 2c。

_DEFAULT_CHANNELS = ("main",)
_FRESH_SEC = 6 * 3600
_EVOLVE_WINDOW_SEC = 3600.0     # 预约轴提前演化窗口（T-1h）


def _scheduled_epoch(raw: str, *, fallback: float) -> float:
    try:
        dt = datetime.fromisoformat(str(raw or "").strip())
    except (TypeError, ValueError):
        return fallback
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _default_hint(share_desire: float = 0.5) -> PerformanceHint:
    return PerformanceHint(
        urgency="normal",
        share_desire=share_desire,
        valid_until=datetime.fromtimestamp(time.time() + _FRESH_SEC, tz=timezone.utc).isoformat(),
    )


def beats_from_landmark_fills(fills: list[dict]) -> list[BeatDraft]:
    """landmark 触发填补项（life.api.fill_due_landmarks 的返回）→ beat 草稿。

    带 landmark_id 的项用确定性幂等键（``beat-lm-<id>``）——与提前演化
    （evolve → 预跑池）对同一地标的生产互斥，总线天然去重，不会开口两次。
    """
    drafts: list[BeatDraft] = []
    for item in fills:
        narrative = str(item.get("hint") or item.get("narrative") or "").strip()
        if not narrative:
            continue
        landmark_id = str(item.get("landmark_id") or "").strip()
        agenda_id = str(item.get("landmark_agenda_id") or "").strip()
        drafts.append(BeatDraft(
            narrative=narrative,
            channels=_DEFAULT_CHANNELS,
            kind="landmark_progress",
            hint=_default_hint(share_desire=float(item.get("salience", 0.6))),
            provenance=BeatProvenance(
                landmark_id=landmark_id or agenda_id,   # 兼容：agenda-only 填充的溯源主键
                agenda_id=agenda_id,
                source_tick=str(item.get("scheduled_at") or ""),
            ),
            beat_id=f"beat-lm-{landmark_id}" if landmark_id else "",
        ))
    return drafts


def beat_from_subjective_event(event: dict, *, source_tick: str = "") -> BeatDraft | None:
    """plan_landmark 的主观事件（subjective_event.hint）→ beat 草稿。"""
    narrative = str(event.get("hint") or "").strip()
    if not narrative or looks_like_artifact(narrative):
        # 结构化残渣（compose 槽位 JSON / 提示词回声）不得进时间轴
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
