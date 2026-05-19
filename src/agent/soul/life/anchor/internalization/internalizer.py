from __future__ import annotations

from datetime import datetime, timezone

from agent.soul.life.experience.anchor_codec import InteractionDirection
from agent.soul.life.experience.unit import ExperienceUnit
from agent.soul.life.orchestrator import ExperienceOrchestrator

from ..chronicle import AnchorChronicleEntry, AnchorChronicleKind, AnchorChronicleStore
from ..inbound.recorder import InboundRecorder
from .buffer import InteractionBuffer
from .session import InteractionSession
from .synthesizer import synthesize_interaction_unit
from .turn import InteractionTurn


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class AnchorInternalizer:
    """Anchor 内化层：Turn 记账 → 会话闭合 → 合成 ExperienceUnit → 编排器。

    - 每轮仍写 Anchor Chronicle（客观账本）
    - 默认不在每轮 ingest；闭合时会话级内化
    - 显著度达阈值的单轮可即时 ingest（例外）
    """

    def __init__(
        self,
        inbound: InboundRecorder,
        orchestrator: ExperienceOrchestrator,
        chronicle: AnchorChronicleStore,
        *,
        turn_promote_threshold: float = 0.65,
        idle_close_sec: float = 1800.0,
    ) -> None:
        self._inbound = inbound
        self._orchestrator = orchestrator
        self._chronicle = chronicle
        self._buffer = InteractionBuffer()
        self._turn_promote_threshold = turn_promote_threshold
        self._idle_close_sec = idle_close_sec

    @property
    def buffer(self) -> InteractionBuffer:
        return self._buffer

    def open_outbound(
        self,
        session_id: str,
        message: str,
        *,
        reason: str = "",
        proactive_intent_id: str = "",
        salience: float = 0.4,
    ) -> InteractionSession:
        session = self._buffer.open(
            session_id,
            InteractionDirection.outbound,
            proactive_intent_id=proactive_intent_id,
            outbound_message=message,
            outbound_reason=reason,
        )
        self._chronicle.append(AnchorChronicleEntry(
            kind=AnchorChronicleKind.interaction_open,
            summary=f"出站：{message[:80]}",
            session_id=session_id,
            salience=salience,
            experience_id=session.id,
        ))
        return session

    def append_inbound_turn(
        self,
        session_id: str,
        user_text: str,
        agent_reply: str,
        *,
        salience: float = 0.3,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        activated_memory_ids: list[str] | None = None,
        proactive_intent_id: str = "",
    ) -> ExperienceUnit:
        existing = self._buffer.get(session_id)
        is_outbound = bool(proactive_intent_id) or (
            existing is not None
            and existing.direction == InteractionDirection.outbound
        )
        direction = (
            InteractionDirection.outbound
            if is_outbound
            else InteractionDirection.inbound
        )
        session = self._buffer.open(
            session_id,
            direction,
            proactive_intent_id=proactive_intent_id,
        )

        unit = self._inbound.record_turn(
            session_id=session_id,
            user_text=user_text,
            agent_reply=agent_reply,
            salience=salience,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            activated_memory_ids=activated_memory_ids,
            proactive_intent_id=proactive_intent_id or session.proactive_intent_id,
        )
        turn = InteractionTurn(
            turn_index=unit.situation.turn_index,
            user_text=user_text,
            agent_reply=agent_reply,
            salience=salience,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            activated_memory_ids=list(activated_memory_ids or []),
            experience_id=unit.id,
        )
        if salience >= self._turn_promote_threshold:
            self._orchestrator.ingest(unit)
            turn.early_ingested = True
        session.turns.append(turn)
        session.touch()
        return unit

    def close_interaction(self, session_id: str) -> ExperienceUnit | None:
        session = self._buffer.pop(session_id)
        if session is None or not session.turns:
            return None

        if session.turn_count == 1 and session.turns[0].early_ingested:
            self._chronicle.append(AnchorChronicleEntry(
                kind=AnchorChronicleKind.interaction_close,
                summary="单轮高显著性已即时内化，跳过会话合成",
                session_id=session_id,
                turn_index=session.turns[0].turn_index,
                salience=session.turns[0].salience,
                experience_id=session.turns[0].experience_id,
            ))
            return None

        unit = synthesize_interaction_unit(session)
        self._chronicle.append(AnchorChronicleEntry(
            kind=AnchorChronicleKind.interaction_close,
            summary=unit.situation.narration[:120],
            session_id=session_id,
            turn_index=unit.situation.turn_index,
            emotion_label=unit.feeling.emotion_label,
            salience=unit.feeling.salience,
            experience_id=unit.id,
        ))
        self._orchestrator.ingest(unit)
        return unit

    def close_idle_sessions(self, *, now: datetime | None = None) -> list[ExperienceUnit]:
        now = now or datetime.now(timezone.utc)
        closed: list[ExperienceUnit] = []
        for sid in list(self._buffer.active_session_ids()):
            session = self._buffer.get(sid)
            if session is None or not session.turns:
                continue
            idle = (now - _parse_iso(session.last_at)).total_seconds()
            if idle >= self._idle_close_sec:
                unit = self.close_interaction(sid)
                if unit is not None:
                    closed.append(unit)
        return closed
