from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.soul.heartbeat.bridge import EmotionalSignal, MemoryHeartbeatResult

from .affect import AffectAnchor
from .store import DriveStateStore

from .capture import (
    CaptureEvent,
    CaptureKind,
    CaptureResult,
    DriveCapture,
    capture_event_from_drive,
)
from .capture.share_buffer import ShareFoldedPackage, fold_share_buffer
from .capture.share_buffer import ShareBuffer, enqueue_share_event
from .expectation import Expectation
from .fsm import DriveContext, DriveEvent, DriveState
from .gate import DriveGate, DriveGateConfig, DriveOutboundRequest
from .share_desire import ShareDesire, max_share_desire


@dataclass
class DriveSession:
    session_id: str
    state: DriveState = field(default_factory=DriveState)
    share_buffer: ShareBuffer = field(default_factory=ShareBuffer)


@dataclass
class DriveSnapshot:
    session_id: str
    state: DriveState = field(default_factory=DriveState)

    @property
    def expectation(self) -> Expectation:
        return self.state.expectation

    @property
    def impulse_level(self) -> float:
        return self.state.impulse_level

    @property
    def ignite_reason(self) -> str:
        return self.state.impulse_reason

    @property
    def share_desire(self) -> ShareDesire:
        return self.state.share_desire

    @property
    def affect(self):
        return self.state.affect


@dataclass
class DriveIngestResult:
    before: DriveSnapshot
    after: DriveSnapshot
    event: CaptureEvent | DriveEvent
    notes: list[str] = field(default_factory=list)
    outbound_request: DriveOutboundRequest | None = None
    boundary: bool = False
    buffered_share_count: int = 0


DriveTransitionResult = DriveIngestResult


class DriveService:
    """Soul 驱动：capture → share buffer → gate → 经 SoulService 向顶层请求。"""

    def __init__(
        self,
        *,
        life_dir: str = "",
        on_outbound_request: Callable[[DriveOutboundRequest], None] | None = None,
        gate_config: DriveGateConfig | None = None,
    ) -> None:
        self._life_dir = life_dir
        self._store = DriveStateStore(life_dir) if life_dir else None
        self._sessions: dict[str, DriveSession] = {}
        if self._store is not None:
            for sid, state in self._store.load_sessions().items():
                self._sessions[sid] = DriveSession(session_id=sid, state=state)
        self._capture = DriveCapture()
        self._gate = DriveGate(gate_config)
        self._on_outbound_request = on_outbound_request

    def snapshot(self, session_id: str) -> DriveSnapshot:
        session = self._session(session_id)
        return DriveSnapshot(session_id=session_id, state=session.state.copy())

    def share_buffer_size(self, session_id: str) -> int:
        return len(self._session(session_id).share_buffer)

    def affect_anchors(self, session_id: str = "tao") -> list[AffectAnchor]:
        return list(self._session(session_id).state.affect.anchors)

    def receive_heartbeat_signal(
        self,
        signal: EmotionalSignal,
        *,
        session_id: str = "tao",
        intensity_floor: float = 0.05,
    ) -> bool:
        """Heartbeat / wander 情绪信号 → Drive.affect 锚点（原 Persona status 路径）。"""
        if signal.intensity < intensity_floor:
            return False
        session = self._session(session_id)
        affect = session.state.affect
        now = datetime.now(timezone.utc).isoformat()
        anchor = AffectAnchor(
            ts=now,
            event=signal.narrative_hint or f"心跳漂移（{signal.dominant_emotion}）",
            felt=f"{signal.dominant_emotion}，烈度 {signal.intensity:.2f}",
        )
        affect.anchors = (affect.anchors + [anchor])[-10:]
        affect.updated_at = now
        if signal.intensity >= 0.3 and signal.narrative_hint.strip():
            affect.texture = signal.narrative_hint.strip()[:200]
        self._persist(session_id)
        return True

    def reset_affect(self, session_id: str = "tao") -> None:
        session = self._session(session_id)
        session.state.reset_affect()
        self._persist(session_id)

    def bind(
        self,
        session_id: str,
        *,
        expectation: Expectation = Expectation.required,
    ) -> DriveSnapshot:
        session = self._session(session_id)
        session.state.expectation = expectation
        session.state.impulse_level = 0.0
        session.state.impulse_reason = ""
        session.state.impulse_source = ""
        session.state.share_desire = ShareDesire.none
        session.share_buffer.clear()
        self._sessions[session_id] = session
        self._persist(session_id)
        return self.snapshot(session_id)

    def ingest(
        self,
        event: DriveEvent,
        *,
        context: DriveContext | None = None,
    ) -> DriveIngestResult:
        capture_event = capture_event_from_drive(event)
        return self._run_capture(capture_event, context=context)

    def capture_evolution(self, event: CaptureEvent) -> DriveIngestResult:
        return self._run_capture(event, context=DriveContext())

    def capture_wander(
        self,
        _result: MemoryHeartbeatResult,
        *,
        session_id: str = "tao",
    ) -> DriveIngestResult | None:
        """禁用客观心跳直推；请走 life 主观 beats 的 capture 链路。"""
        _ = session_id
        return None

    def dispatch(
        self,
        event: DriveEvent,
        *,
        context: DriveContext | None = None,
    ) -> DriveIngestResult:
        return self.ingest(event, context=context)

    def consider_heartbeat_signal(
        self,
        result: MemoryHeartbeatResult,
        *,
        session_id: str = "tao",
    ) -> DriveIngestResult | None:
        return self.capture_wander(result, session_id=session_id)

    def set_outbound_handler(
        self,
        handler: Callable[[DriveOutboundRequest], None] | None,
    ) -> None:
        self._on_outbound_request = handler

    @property
    def moderate_threshold(self) -> float:
        return self._gate.moderate_threshold

    def flush_accumulated(
        self,
        session_id: str = "tao",
        *,
        source: str = "manual_flush",
        wait_reply: bool = True,
        expectation: Expectation = Expectation.required,
    ) -> DriveOutboundRequest | None:
        session = self._session(session_id)
        return self._flush_session_accumulated(
            session_id=session_id,
            session=session,
            source=source,
            wait_reply=wait_reply,
            expectation=expectation,
            require_saturated=True,
        )

    def _run_capture(
        self,
        event: CaptureEvent,
        *,
        context: DriveContext | None,
    ) -> DriveIngestResult:
        sid = event.session_id
        session = self._session(sid)
        before = self.snapshot(sid)
        ctx = context or DriveContext()
        flushed_on_external_start = False

        if event.kind == CaptureKind.user_text and not ctx.line_open:
            self._flush_session_accumulated(
                session_id=sid,
                session=session,
                source="external_start_flush",
                wait_reply=False,
                expectation=Expectation.none,
                require_saturated=False,
            )
            session.state.expectation = Expectation.none
            flushed_on_external_start = True

        capture_result = self._capture.ingest(session.state, event, ctx)
        if not capture_result.boundary:
            enqueue_share_event(session.share_buffer, event)

        outbound = self._gate.evaluate(capture_result, session.share_buffer)
        if outbound is not None:
            session.state.discharge_impulse(outbound.impulse_level)
            session.share_buffer.clear()
            if self._on_outbound_request is not None:
                self._on_outbound_request(outbound)

        self._sessions[sid] = session
        self._persist(sid)
        after = self.snapshot(sid)

        return DriveIngestResult(
            before=before,
            after=after,
            event=event,
            notes=(
                ["drive: flushed accumulated impulse on external start"]
                if flushed_on_external_start
                else []
            ) + list(capture_result.notes),
            outbound_request=outbound,
            boundary=capture_result.boundary,
            buffered_share_count=len(session.share_buffer),
        )

    def _session(self, session_id: str) -> DriveSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = DriveSession(session_id=session_id)
        return self._sessions[session_id]

    def _fold_or_none(
        self,
        session: DriveSession,
    ) -> ShareFoldedPackage | None:
        package = fold_share_buffer(session.share_buffer.entries, session.state)
        if not package.summary.strip():
            return None
        return package

    def _flush_session_accumulated(
        self,
        *,
        session_id: str,
        session: DriveSession,
        source: str,
        wait_reply: bool,
        expectation: Expectation,
        require_saturated: bool,
    ) -> DriveOutboundRequest | None:
        if require_saturated and session.state.impulse_level < self._gate.moderate_threshold:
            return None
        package = self._fold_or_none(session)
        if package is None:
            return None
        share_desire = max_share_desire(package.peak_share_desire, session.state.share_desire)
        request = DriveOutboundRequest(
            session_id=session_id,
            reason=package.summary,
            impulse_level=session.state.impulse_level,
            share_desire=share_desire,
            expectation=expectation,
            package=package,
            source=source,
            wait_reply=wait_reply,
        )
        session.state.impulse_level = 0.0
        session.state.impulse_reason = ""
        session.state.impulse_source = ""
        session.state.share_desire = ShareDesire.none
        session.share_buffer.clear()
        if self._on_outbound_request is not None:
            self._on_outbound_request(request)
        self._persist(session_id)
        return request

    def _persist(self, session_id: str) -> None:
        if self._store is None:
            return
        self._store.save_sessions(
            {sid: sess.state for sid, sess in self._sessions.items()}
        )


DriveLayer = DriveService
