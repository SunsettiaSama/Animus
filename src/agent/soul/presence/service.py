from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from agent.soul.heartbeat.bridge import EmotionalSignal, MemoryHeartbeatResult

from .fsm import (
    ExpectationScanMode,
    ExpectationScanResult,
    PresenceContext,
    PresenceEvent,
    PresenceState,
    REPLY_URGE_THRESHOLD,
    fold_share_queue,
    scan_expectation_thresholds,
)
from .interface import (
    CaptureEvent,
    CaptureKind,
    PresenceInterface,
    PresenceTriggerResult,
    SpeakInterface,
    SpeakInterfaceConfig,
    SpeakRequest,
    ShareFoldedPackage,
)
from .share_desire import ShareDesire, max_share_desire
from .store import PresenceStateStore, StoredPresenceSession
from .transition import (
    DialogueExperience,
    DialogueFsmRefresher,
    DialogueObserveResult,
    DialogueSessionTransition,
    IncidentFsmRefresher,
    IncidentIngestResult,
    IncidentKind,
    IncidentTransition,
    LifeIncident,
    PresenceTransitionEngine,
    PresenceTrigger,
    RuminationFsmRefresher,
    RuminationIngestResult,
    RuminationSignal,
    RuminationTransition,
    Expectation,
    PresenceInteraction,
    PresenceWakeEngine,
    SleepResult,
    WakeContext,
    WakeResult,
)

def capture_event_from_presence(event: PresenceEvent) -> CaptureEvent:
    return CaptureEvent(
        kind=CaptureKind(event.kind.value),
        session_id=event.session_id,
        payload=dict(event.payload),
    )


def capture_event_from_wander(
    _result: object,
    *,
    session_id: str = "tao",
) -> CaptureEvent | None:
    _ = session_id
    return None


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
    event: CaptureEvent | PresenceEvent
    notes: list[str] = field(default_factory=list)
    speak_request: SpeakRequest | None = None
    boundary: bool = False
    buffered_share_count: int = 0

    @property
    def outbound_request(self) -> SpeakRequest | None:
        return self.speak_request


PresenceTransitionResult = PresenceIngestResult


class PresenceService:
    """Soul 当下态：transition（状态转移）+ interface（对外 speak 接口）。"""

    def __init__(
        self,
        *,
        life_dir: str = "",
        on_speak_request: Callable[[SpeakRequest], None] | None = None,
        on_outbound_request: Callable[[SpeakRequest], None] | None = None,
        interface_config: SpeakInterfaceConfig | None = None,
        wake_engine: PresenceWakeEngine | None = None,
        transition_engine: PresenceTransitionEngine | None = None,
        dialogue_transition: DialogueSessionTransition | None = None,
        dialogue_refresher: DialogueFsmRefresher | None = None,
        incident_transition: IncidentTransition | None = None,
        incident_refresher: IncidentFsmRefresher | None = None,
        rumination_transition: RuminationTransition | None = None,
        rumination_refresher: RuminationFsmRefresher | None = None,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self._life_dir = life_dir
        self._timezone = timezone
        if transition_engine is not None:
            self._transition_engine = transition_engine
        else:
            self._transition_engine = PresenceTransitionEngine.from_refreshers(
                dialogue_transition=dialogue_transition,
                dialogue_refresher=dialogue_refresher,
                incident_transition=incident_transition,
                incident_refresher=incident_refresher,
                rumination_transition=rumination_transition,
                rumination_refresher=rumination_refresher,
                wake_engine=wake_engine,
            )
        self._wake_engine = self._transition_engine.wake_engine
        self._dialogue_transition = self._transition_engine.dialogue
        self._incident_transition = self._transition_engine.incident
        self._rumination_transition = self._transition_engine.rumination
        self._store = PresenceStateStore(life_dir) if life_dir else None
        self._sessions: dict[str, PresenceSession] = {}
        if self._store is not None:
            for sid, stored in self._store.load_sessions().items():
                self._sessions[sid] = PresenceSession(
                    session_id=sid,
                    state=stored.state,
                    interaction=stored.interaction,
                    awake=stored.awake,
                    last_wake_date=stored.last_wake_date,
                )
        self._egress = SpeakInterface(interface_config)
        self._interface = self._egress
        self._on_speak_request = on_speak_request or on_outbound_request
        self.ingress = PresenceInterface(self)
        self.interface = self.ingress
        self.egress = self._egress

    def snapshot(self, session_id: str) -> PresenceSnapshot:
        session = self._session(session_id)
        return PresenceSnapshot(
            session_id=session_id,
            state=session.state.copy(),
            interaction=session.interaction.copy(),
        )

    def share_queue_size(self, session_id: str) -> int:
        return len(self._session(session_id).state.expectation.share_queue)

    def share_buffer_size(self, session_id: str) -> int:
        """兼容别名 → share_queue_size。"""
        return self.share_queue_size(session_id)

    def set_wake_engine(self, engine: PresenceWakeEngine | None) -> None:
        self._transition_engine.wake_engine = engine or PresenceWakeEngine()
        self._wake_engine = self._transition_engine.wake_engine

    def trigger(self, trigger: PresenceTrigger) -> PresenceTriggerResult:
        """兼容入口 → interface.trigger。"""
        return self.interface.trigger(trigger)

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

    def observe_dialogue_turn(
        self,
        session_id: str,
        *,
        user_text: str,
        agent_text: str,
    ) -> DialogueObserveResult:
        """记录一轮对话块；按 k 块刷新 FSM，维护连续体验（不逐轮硬写 FSM）。"""
        result = self.trigger(
            PresenceTrigger.dialogue(
                session_id,
                user_text=user_text,
                agent_text=agent_text,
            ),
        )
        if result.outcome.dialogue is None:
            raise RuntimeError("dialogue trigger did not produce DialogueObserveResult")
        return result.outcome.dialogue

    def finalize_dialogue_experience(self, session_id: str) -> DialogueExperience | None:
        """会话闭合：导出 Presence 连续体验并重置对话 tracker。"""
        session = self._session(session_id)
        experience = self._dialogue_transition.finalize(
            session.state,
            session_id=session_id,
        )
        if experience is not None:
            self._persist(session_id)
        return experience

    def build_story_beat_event(
        self,
        session_id: str,
        *,
        hint: str,
        salience: float = 0.4,
        trigger: str = "",
        share_desire: str | None = None,
        emotion_text: str = "",
        emotion_intensity: float = 0.0,
        emotion_strength: str = "",
    ) -> CaptureEvent:
        return CaptureEvent.story_beat(
            session_id,
            hint=hint,
            salience=salience,
            trigger=trigger,
            share_desire=share_desire,
            emotion_text=emotion_text,
            emotion_intensity=emotion_intensity,
            emotion_strength=emotion_strength,
        )

    def ingest_incident(self, incident: LifeIncident) -> IncidentIngestResult:
        """Life 事件注入 → transition/incident 刷新 FSM。"""
        result = self.trigger(PresenceTrigger.incident(incident))
        if result.outcome.incident is None:
            raise RuntimeError("incident trigger did not produce IncidentIngestResult")
        return result.outcome.incident

    def ingest_rumination(self, rumination: RuminationSignal) -> RuminationIngestResult:
        """记忆反刍注入 → transition/rumination 刷新 FSM。"""
        result = self.trigger(PresenceTrigger.rumination(rumination))
        if result.outcome.rumination is None:
            raise RuntimeError("rumination trigger did not produce RuminationIngestResult")
        return result.outcome.rumination

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
        session.state.expectation.share_queue.drain()
        self._sessions[session_id] = session
        self._persist(session_id)
        return self.snapshot(session_id)

    def ingest(
        self,
        event: PresenceEvent,
        *,
        context: PresenceContext | None = None,
    ) -> PresenceIngestResult:
        return self.interface.boundary(event, context=context)

    def capture_evolution(self, event: CaptureEvent) -> PresenceIngestResult:
        return self.interface.capture(event)

    def capture_wander(
        self,
        _result: MemoryHeartbeatResult,
        *,
        session_id: str = "tao",
    ) -> PresenceIngestResult | None:
        _ = session_id
        return None

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
    ) -> PresenceIngestResult | None:
        return self.capture_wander(result, session_id=session_id)

    def set_speak_handler(
        self,
        handler: Callable[[SpeakRequest], None] | None,
    ) -> None:
        self._on_speak_request = handler

    set_outbound_handler = set_speak_handler

    @property
    def moderate_threshold(self) -> float:
        return self._interface.moderate_threshold

    def flush_accumulated(
        self,
        session_id: str = "tao",
        *,
        source: str = "manual_flush",
        wait_reply: bool = True,
        expectation: Expectation = Expectation.required,
    ) -> SpeakRequest | None:
        session = self._session(session_id)
        return self._flush_session_accumulated(
            session_id=session_id,
            session=session,
            source=source,
            wait_reply=wait_reply,
            expectation=expectation,
            require_saturated=True,
        )

    def scan_expectation_drives(self, session_id: str = "tao") -> ExpectationScanResult:
        """扫描 FSM 期待驱动：超阈值则 proactive 开聊或对话内追加。"""
        session = self._session(session_id)
        line_open = session.interaction.expectation != Expectation.none
        scan = scan_expectation_thresholds(
            session_id=session_id,
            expectation=session.state.expectation,
            interaction=session.interaction,
            line_open=line_open,
        )
        if not scan.triggered or scan.speak_request is None:
            return scan

        if scan.mode == ExpectationScanMode.append_message:
            session.state.expectation.discharge_reply_urge(REPLY_URGE_THRESHOLD)
        elif scan.mode == ExpectationScanMode.proactive_open:
            session.state.expectation.reset_after_proactive_open()

        session.interaction.impulse_level = 0.0
        session.interaction.impulse_reason = ""
        session.interaction.impulse_source = ""
        session.interaction.share_desire = ShareDesire.none

        if self._on_speak_request is not None:
            self._on_speak_request(scan.speak_request)
        self._persist(session_id)
        return scan

    def _maybe_scan_expectation(self, session_id: str) -> ExpectationScanResult | None:
        session = self._session(session_id)
        exp = session.state.expectation
        if not exp.at_proactive_threshold() and not (
            session.interaction.expectation != Expectation.none and exp.wants_multi_reply()
        ):
            return None
        return self.scan_expectation_drives(session_id)

    def _session(self, session_id: str) -> PresenceSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = PresenceSession(session_id=session_id)
        return self._sessions[session_id]

    def _fold_or_none(
        self,
        session: PresenceSession,
    ) -> ShareFoldedPackage | None:
        package = fold_share_queue(
            session.state.expectation.share_queue,
            session.interaction,
        )
        if not package.summary.strip():
            return None
        return package

    def _flush_session_accumulated(
        self,
        *,
        session_id: str,
        session: PresenceSession,
        source: str,
        wait_reply: bool,
        expectation: Expectation,
        require_saturated: bool,
    ) -> SpeakRequest | None:
        interaction = session.interaction
        if require_saturated and interaction.impulse_level < self._interface.moderate_threshold:
            return None
        package = self._fold_or_none(session)
        if package is None:
            return None
        share_desire = max_share_desire(package.peak_share_desire, interaction.share_desire)
        request = SpeakRequest(
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
        session.state.expectation.share_queue.drain()
        if self._on_speak_request is not None:
            self._on_speak_request(request)
        self._persist(session_id)
        return request

    def _persist(self, session_id: str) -> None:
        if self._store is None:
            return
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

    def _today(self) -> str:
        return datetime.now(ZoneInfo(self._timezone)).date().isoformat()


PresenceLayer = PresenceService
