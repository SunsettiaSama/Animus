from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from agent.soul.heartbeat.bridge import EmotionalSignal, MemoryHeartbeatResult

from .discharge import ImpulseDischarge
from .gateway_result import GatewayResult
from .gateway import PresenceGateway
from .narrative import compose_self_narrative
from .state_block import PresenceStateBlock
from .channel_store import ChannelShareSnapshotStore, ShareProductionAnnotation
from .share_desire import (
    OUTBOUND_THRESHOLD_MODERATE,
    ShareDesire,
    StaticStatePatch,
    max_share_desire,
)
from .state import (
    ExpectationScanMode,
    ExpectationScanResult,
    PresenceContext,
    PresenceEvent,
    PresenceState,
    REPLY_URGE_THRESHOLD,
    fold_share_queue,
    scan_expectation_thresholds,
)
from .store import PresenceStateStore, StoredPresenceSession
from .transition import (
    PresenceTransitionRouter,
    PresenceTrigger,
    Expectation,
    PresenceInteraction,
    SleepResult,
    WakeContext,
    WakeResult,
)
from .transition.ports import TransitionHandler
from .transition.trigger import PresenceTriggerKind
from infra.llm import BaseLLM
from agent.soul.life.anchor.presence_bundle import PresenceExperienceBundle

if TYPE_CHECKING:
    from agent.soul.life.experience.domain.unit import ExperienceUnit
    from agent.soul.life.experience.unit_layer.manage.log import ExperienceLog
    from agent.soul.life.experience.hub import LifeExperienceStack

PresenceTriggerResult = GatewayResult


@dataclass
class PresenceSession:
    session_id: str
    state: PresenceState = field(default_factory=PresenceState)
    interaction: PresenceInteraction = field(default_factory=PresenceInteraction)
    awake: bool = False
    last_wake_date: str = ""


@dataclass
class PresenceSnapshot:
    session_id: str
    state: PresenceState = field(default_factory=PresenceState)
    interaction: PresenceInteraction = field(default_factory=PresenceInteraction)

    @property
    def expectation(self) -> Expectation:
        return self.interaction.expectation

    @property
    def impulse_level(self) -> float:
        return self.interaction.impulse_level

    @property
    def ignite_reason(self) -> str:
        return self.interaction.impulse_reason

    @property
    def share_desire(self) -> ShareDesire:
        return self.interaction.share_desire

    @property
    def toward_user_expectation(self) -> float:
        return self.state.expectation.toward_user

    @property
    def reply_urge(self) -> float:
        return self.state.expectation.reply_urge

    @property
    def proactive_ready(self) -> bool:
        return self.state.expectation.at_proactive_threshold()

    @property
    def wants_multi_reply(self) -> bool:
        return self.state.expectation.wants_multi_reply()

    @property
    def affect(self):
        return self.state.affect


@dataclass
class PresenceIngestResult:
    before: PresenceSnapshot
    after: PresenceSnapshot
    event: PresenceEvent
    notes: list[str] = field(default_factory=list)
    boundary: bool = False
    buffered_share_count: int = 0
    impulse_discharge: ImpulseDischarge | None = None


PresenceTransitionResult = PresenceIngestResult

PresenceStatusUpdateListener = Callable[["PresenceSnapshot"], None]


class PresenceService:
    """Soul 当下态：仅维护 state + transition + gateway 入站。"""

    def __init__(
        self,
        *,
        life_dir: str = "",
        transition_router: PresenceTransitionRouter | None = None,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self._life_dir = life_dir
        self._timezone = timezone
        self._transition_router = transition_router or PresenceTransitionRouter()
        self._store = PresenceStateStore(life_dir) if life_dir else None
        self._channel_store = ChannelShareSnapshotStore(life_dir) if life_dir else None
        self._sessions: dict[str, PresenceSession] = {}
        self._status_update_listeners: list[PresenceStatusUpdateListener] = []
        self._life_experience: LifeExperienceStack | None = None
        self._unit_ingest_counters: dict[str, int] = {}
        self._unit_distill_writer = None
        if self._store is not None:
            for sid, stored in self._store.load_sessions().items():
                self._sessions[sid] = PresenceSession(
                    session_id=sid,
                    state=stored.state,
                    interaction=stored.interaction,
                    awake=stored.awake,
                    last_wake_date=stored.last_wake_date,
                )
        self.gateway = PresenceGateway(self)
        self.interface = self.gateway
        self._io_hub = None

    @property
    def io(self):
        if self._io_hub is None:
            raise RuntimeError("PresenceService 未 bind_io")
        return self._io_hub

    def bind_io(self, hub) -> None:
        self._io_hub = hub

    def register_status_update_listener(
        self,
        listener: PresenceStatusUpdateListener,
    ) -> None:
        """注册状态更新通知（service 层推送给 speak 等下游）。"""
        self._status_update_listeners.append(listener)

    def bind_life_experience(self, stack: LifeExperienceStack) -> None:
        """Presence ↔ Life 双向绑定：pull_and_sync 从 stack.log 读取热体验。"""
        self._life_experience = stack

    def bind_unit_distill_llm(self, llm: BaseLLM) -> None:
        from .unit_distill import PresenceUnitDistillWriter

        self._unit_distill_writer = PresenceUnitDistillWriter(llm)

    @property
    def life_experience(self) -> LifeExperienceStack | None:
        return self._life_experience

    def sync_from_life(
        self,
        session_id: str = "tao",
        *,
        hot_hours: float | None = 2,
        tail: int = 12,
    ) -> dict[str, object]:
        if self._life_experience is None:
            raise RuntimeError("PresenceService 未 bind_life_experience")
        return self.pull_and_sync_from_life(
            self._life_experience.log,
            session_id,
            hours=hot_hours,
            tail=tail,
        )

    def snapshot(self, session_id: str) -> PresenceSnapshot:
        session = self._session(session_id)
        return PresenceSnapshot(
            session_id=session_id,
            state=session.state.copy(),
            interaction=session.interaction.copy(),
        )

    def compose_self_narrative(self, session_id: str = "tao") -> str:
        session = self._session(session_id)
        return compose_self_narrative(session.state, session.interaction)

    def sync_life_bundle(self, bundle: PresenceExperienceBundle) -> dict[str, list[str]]:
        """life 字段包 → static（life session）+ 分享标注（channel 权威）。"""
        life_sid = (bundle.session_id or "tao").strip() or "tao"
        channel_id = (bundle.channel_id or bundle.target_channel_id or "").strip()

        # life session 只吃 static；有 channel 时分享不写入 tao 队列
        life_bundle = bundle
        if channel_id and (bundle.enqueue_share or bundle.push_to_user):
            life_bundle = PresenceExperienceBundle.from_dict(bundle.to_dict())
            life_bundle.enqueue_share = False
            life_bundle.push_to_user = False
            life_bundle.share_content = ""

        result = self.trigger(PresenceTrigger.life_sync(life_bundle))
        self._persist(life_sid)
        sync = result.outcome.life_sync
        notes = list(result.notes)

        annotation = ShareProductionAnnotation(
            session_id=life_sid,
            channel_id=channel_id,
            unit_id=bundle.experience_id,
            source=bundle.source,
            decided=bool(bundle.annotation_decided),
            enqueue_share=bool(bundle.enqueue_share),
            push_to_user=bool(bundle.push_to_user),
            share_content=bundle.share_content,
            share_why=bundle.share_why,
            share_desire=bundle.share_desire,
            promote_to_memory=bool(bundle.promote_to_memory),
            impression_intensity=float(bundle.impression_intensity or 0.0),
            impression_why=bundle.impression_why,
            note="" if bundle.annotation_decided else "undecided",
        )
        if self._channel_store is not None:
            self._channel_store.append_annotation(annotation)

        if channel_id and (bundle.enqueue_share or bundle.push_to_user) and bundle.share_content.strip():
            share_session = self._session(channel_id)
            from .transition.dynamic.life_meta import apply_dynamic_bundle

            share_notes = apply_dynamic_bundle(
                share_session.state,
                share_session.interaction,
                bundle,
            )
            notes.extend(share_notes)
            self._persist(channel_id)
            self._mirror_channel_share_state(channel_id, share_session)
        elif not channel_id and (bundle.enqueue_share or bundle.push_to_user):
            notes.append("share: no target_channel_id — recorded in life pool only")

        self._notify_status_update(self.snapshot(life_sid))
        if channel_id:
            self._notify_status_update(self.snapshot(channel_id))
        return {
            "static_notes": list(sync.static_notes) if sync else [],
            "dynamic_notes": list(sync.dynamic_notes) if sync else [],
            "notes": notes,
        }

    def _mirror_channel_share_state(self, channel_id: str, session: PresenceSession) -> None:
        if self._channel_store is None:
            return
        from .channel_store import ChannelShareState

        state = ChannelShareState(
            channel_id=channel_id,
            share_queue=session.state.expectation.share_queue.copy(),
            pending_push=bool(session.state.expectation.pending_push),
            last_share_why=session.state.expectation.reason,
        )
        self._channel_store.save_share_state(state)

    def archive_and_drain_share_queue(self, session_id: str, *, reason: str) -> list:
        session = self._session(session_id)
        drained = session.state.expectation.share_queue.drain()
        session.state.expectation.pending_push = False
        if drained and self._channel_store is not None:
            self._channel_store.archive_intents(session_id, drained, reason=reason)
        return drained

    def on_unit_ingested(
        self,
        unit: ExperienceUnit,
        log: ExperienceLog | None = None,
    ) -> None:
        """单条 unit 入库：时段情绪 + 按批次蒸馏近期经历画像。"""
        from config.soul.presence.config import (
            UNIT_DISTILL_BATCH_K,
            UNIT_DISTILL_MAX_CHARS,
        )

        from .lingering import apply_unit_lingering
        from .unit_distill.queue import select_distill_batch

        session_id = unit.situation.session_id or "tao"
        session = self._session(session_id)
        apply_unit_lingering(session.state, unit)

        counter = self._unit_ingest_counters.get(session_id, 0) + 1
        self._unit_ingest_counters[session_id] = counter
        batch_k = UNIT_DISTILL_BATCH_K

        if (
            counter % batch_k == 0
            and log is not None
            and self._unit_distill_writer is not None
        ):
            portrait_state = session.state.recent_portrait
            batch = select_distill_batch(
                log,
                session_id,
                batch_k=batch_k,
                last_distilled_unit_id=portrait_state.last_distilled_unit_id,
            )
            if batch:
                session.state.recent_portrait = self._unit_distill_writer.distill_batch(
                    batch,
                    max_chars=UNIT_DISTILL_MAX_CHARS,
                )

        self._persist(session_id)

    def pull_and_sync_from_life(
        self,
        log: ExperienceLog,
        session_id: str = "tao",
        *,
        hours: float | None = 2,
        tail: int = 12,
    ) -> dict[str, object]:
        from agent.soul.life.experience.ingest.presence import supply_presence_bundle_from_life

        bundle = supply_presence_bundle_from_life(
            log, session_id, hours=hours, tail=tail,
        )
        if bundle is None:
            return {"applied": False, "reason": "no hot experience", "session_id": session_id}
        sync = self.sync_life_bundle(bundle)
        return {
            "applied": True,
            "session_id": session_id,
            "bundle_source": bundle.source,
            **sync,
        }

    def apply_state_block(self, block: PresenceStateBlock) -> list[str]:
        """外部体验/反刍块 → 统一 life_sync 双链路。"""
        from agent.soul.life.experience.ingest.presence import presence_bundle_from_state_block

        sync = self.sync_life_bundle(presence_bundle_from_state_block(block))
        return list(sync.get("notes", []))

    def share_queue_size(self, session_id: str) -> int:
        return len(self._session(session_id).state.expectation.share_queue)

    def pop_share_intent(self, session_id: str):
        """弹出最想分享的一条并持久化（供 speak state:share 交接）。"""
        session = self._session(session_id)
        intent = session.state.expectation.share_queue.pop_most_wanted()
        if intent is None:
            return None
        self._persist(session_id)
        snap = self.snapshot(session_id)
        self._notify_status_update(snap)
        return intent

    def pop_top_share_intents(self, session_id: str, *, limit: int = 2) -> list:
        """弹出 salience 最高的若干条（不全量 drain，供活跃会话延迟注入）。"""
        session = self._session(session_id)
        popped = []
        for _ in range(max(0, limit)):
            intent = session.state.expectation.share_queue.pop_most_wanted()
            if intent is None:
                break
            popped.append(intent)
        if popped:
            self._persist(session_id)
            self._notify_status_update(self.snapshot(session_id))
        return popped

    def consume_share_at(self, session_id: str, queue_index: int) -> bool:
        """按队列下标移除一条分享意图（guidance 规划抛出后消费）。"""
        session = self._session(session_id)
        intent = session.state.expectation.share_queue.pop_at(queue_index)
        if intent is None:
            return False
        self._persist(session_id)
        self._notify_status_update(self.snapshot(session_id))
        return True

    def _notify_status_update(self, snap: PresenceSnapshot) -> None:
        for listener in self._status_update_listeners:
            listener(snap)

    def register_transition(
        self,
        kind: PresenceTriggerKind,
        handler: TransitionHandler,
    ) -> None:
        self._transition_router.register(kind, handler)

    def patch_static(self, session_id: str, patch: StaticStatePatch) -> PresenceSnapshot:
        session = self._session(session_id)
        if patch.affect is not None:
            session.state.affect.narrative = patch.affect
        if patch.somatic is not None:
            session.state.somatic.narrative = patch.somatic
        if patch.thinking is not None:
            session.state.cognition.thinking = patch.thinking
        if patch.perception is not None:
            session.state.perception.narrative = patch.perception
        self._persist(session_id)
        return self.snapshot(session_id)

    def set_working_memory(self, session_id: str, text: str) -> None:
        session = self._session(session_id)
        session.state.cognition.working_memory = text
        self._persist(session_id)

    def apply_dialogue_session_boundary(self, session_id: str) -> list[str]:
        from .transition.static.lifecycle import apply_dialogue_session_boundary

        session = self._session(session_id)
        notes = apply_dialogue_session_boundary(session.state)
        self._persist(session_id)
        self._notify_status_update(self.snapshot(session_id))
        return notes

    def trigger(self, trigger: PresenceTrigger) -> GatewayResult:
        return self.gateway.trigger(trigger)

    def set_timezone(self, timezone: str) -> None:
        self._timezone = timezone

    def is_awake(self, session_id: str = "tao") -> bool:
        session = self._session(session_id)
        today = self._today()
        return session.awake and session.last_wake_date == today

    def wake_up(
        self,
        session_id: str = "tao",
        *,
        context: WakeContext | None = None,
        force: bool = False,
    ) -> WakeResult:
        result = self.trigger(
            PresenceTrigger.wake(session_id, context=context, force=force),
        )
        if result.outcome.wake is None:
            raise RuntimeError("wake trigger did not produce WakeResult")
        return result.outcome.wake

    def sleep(self, session_id: str = "tao") -> SleepResult:
        result = self.trigger(PresenceTrigger.sleep(session_id))
        if result.outcome.sleep is None:
            raise RuntimeError("sleep trigger did not produce SleepResult")
        return result.outcome.sleep

    def affect_narrative(self, session_id: str = "tao") -> str:
        return self._session(session_id).state.affect.narrative

    def receive_heartbeat_signal(
        self,
        signal: EmotionalSignal,
        *,
        session_id: str = "tao",
        intensity_floor: float = 0.05,
    ) -> bool:
        if signal.intensity < intensity_floor:
            return False
        session = self._session(session_id)
        line = signal.narrative_hint.strip()
        if not line:
            emotion = signal.dominant_emotion.strip()
            line = f"心里浮过一丝{emotion}" if emotion else "有某种情绪轻轻掠过"
        session.state.affect.append(line)
        self._persist(session_id)
        return True

    def reset_affect(self, session_id: str = "tao") -> None:
        session = self._session(session_id)
        session.state.reset_affect()
        self._persist(session_id)

    def inject_boundary_event(
        self,
        event: PresenceEvent,
        *,
        context: PresenceContext | None = None,
    ) -> PresenceIngestResult:
        """边界事件注入 → transition 期待 FSM。"""
        return self.ingest(event, context=context)

    def bind(
        self,
        session_id: str,
        *,
        expectation: Expectation = Expectation.required,
    ) -> PresenceSnapshot:
        session = self._session(session_id)
        session.interaction.expectation = expectation
        session.interaction.impulse_level = 0.0
        session.interaction.impulse_reason = ""
        session.interaction.impulse_source = ""
        session.interaction.share_desire = ShareDesire.none
        self.archive_and_drain_share_queue(session_id, reason="bind")
        self._sessions[session_id] = session
        self._persist(session_id)
        return self.snapshot(session_id)

    def ingest(
        self,
        event: PresenceEvent,
        *,
        context: PresenceContext | None = None,
    ) -> PresenceIngestResult:
        return self.gateway.boundary(event, context=context)

    def dispatch(
        self,
        event: PresenceEvent,
        *,
        context: PresenceContext | None = None,
    ) -> PresenceIngestResult:
        return self.ingest(event, context=context)

    def consider_heartbeat_signal(
        self,
        result: MemoryHeartbeatResult,
        *,
        session_id: str = "tao",
    ) -> bool:
        return self.receive_heartbeat_signal(
            result.signal,
            session_id=session_id,
        )

    @property
    def moderate_threshold(self) -> float:
        return OUTBOUND_THRESHOLD_MODERATE

    def discharge_accumulated(
        self,
        session_id: str = "tao",
        *,
        source: str = "manual_flush",
        wait_reply: bool = True,
        expectation: Expectation = Expectation.required,
        require_saturated: bool = True,
    ) -> ImpulseDischarge | None:
        session = self._session(session_id)
        return self._discharge_session_accumulated(
            session_id=session_id,
            session=session,
            source=source,
            wait_reply=wait_reply,
            expectation=expectation,
            require_saturated=require_saturated,
        )

    flush_accumulated = discharge_accumulated

    def scan_expectation(self, session_id: str = "tao") -> ExpectationScanResult:
        """扫描 FSM 期待驱动并应用状态侧效应（不触发 speak）。"""
        session = self._session(session_id)
        line_open = session.interaction.expectation != Expectation.none
        scan = scan_expectation_thresholds(
            session_id=session_id,
            expectation=session.state.expectation,
            interaction=session.interaction,
            line_open=line_open,
        )
        if not scan.triggered or scan.payload is None:
            return scan

        if scan.mode == ExpectationScanMode.append_message:
            session.state.expectation.discharge_reply_urge(REPLY_URGE_THRESHOLD)
        elif scan.mode == ExpectationScanMode.proactive_open:
            self.archive_and_drain_share_queue(session_id, reason="proactive_open")
            session.state.expectation.toward_user = 0.0
            session.state.expectation.pending_push = False
            session.state.expectation.reason = ""
            session.state.expectation.source = ""

        session.interaction.impulse_level = 0.0
        session.interaction.impulse_reason = ""
        session.interaction.impulse_source = ""
        session.interaction.share_desire = ShareDesire.none
        self._persist(session_id)
        if self._channel_store is not None:
            self._mirror_channel_share_state(session_id, session)
        return scan

    def _maybe_scan_expectation(self, session_id: str) -> ExpectationScanResult | None:
        session = self._session(session_id)
        exp = session.state.expectation
        if not exp.at_proactive_threshold() and not (
            session.interaction.expectation != Expectation.none and exp.wants_multi_reply()
        ):
            return None
        return self.scan_expectation(session_id)

    scan_expectation_drives = scan_expectation

    def _session(self, session_id: str) -> PresenceSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = PresenceSession(session_id=session_id)
        return self._sessions[session_id]

    def _fold_or_none(self, session: PresenceSession):
        package = fold_share_queue(
            session.state.expectation.share_queue,
            session.interaction,
        )
        if not package.summary.strip():
            return None
        return package

    def _discharge_session_accumulated(
        self,
        *,
        session_id: str,
        session: PresenceSession,
        source: str,
        wait_reply: bool,
        expectation: Expectation,
        require_saturated: bool,
    ) -> ImpulseDischarge | None:
        interaction = session.interaction
        if require_saturated:
            push_ready = (
                session.state.expectation.pending_push
                or session.state.expectation.share_queue.has_push_intent()
            )
            if not push_ready and interaction.impulse_level < self.moderate_threshold:
                return None
        package = self._fold_or_none(session)
        if package is None:
            return None
        share_desire = max_share_desire(package.peak_share_desire, interaction.share_desire)
        discharge = ImpulseDischarge(
            session_id=session_id,
            reason=package.summary,
            impulse_level=interaction.impulse_level,
            share_desire=share_desire,
            expectation=expectation,
            package=package,
            source=source,
            wait_reply=wait_reply,
        )
        interaction.impulse_level = 0.0
        interaction.impulse_reason = ""
        interaction.impulse_source = ""
        interaction.share_desire = ShareDesire.none
        self.archive_and_drain_share_queue(session_id, reason=f"discharge:{source}")
        self._persist(session_id)
        return discharge

    def _persist(self, session_id: str) -> None:
        if self._store is not None:
            self._store.save_sessions(
                {
                    sid: StoredPresenceSession(
                        state=sess.state,
                        interaction=sess.interaction,
                        awake=sess.awake,
                        last_wake_date=sess.last_wake_date,
                    )
                    for sid, sess in self._sessions.items()
                }
            )
        self._emit_status_update(session_id)

    def _emit_status_update(self, session_id: str) -> None:
        if not self._status_update_listeners:
            return
        snap = self.snapshot(session_id)
        for listener in self._status_update_listeners:
            listener(snap)

    def _today(self) -> str:
        return datetime.now(ZoneInfo(self._timezone)).date().isoformat()
