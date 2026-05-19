from __future__ import annotations

from ...experience.anchor_codec import AnchorUnitContext, InteractionDirection, stamp_anchor_context
from ...experience.sources import ExperienceSource
from ...experience.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from ...orchestrator import ExperienceOrchestrator
from ..chronicle import AnchorChronicleEntry, AnchorChronicleKind, AnchorChronicleStore


class InboundRecorder:
    """入站链路：Tao 顶层用户输入 → Anchor Chronicle + ExperienceOrchestrator。

    Chronicle 写入在本模块完成；编排器只负责热存储 / STM / 交会折叠。
    """

    def __init__(
        self,
        orchestrator: ExperienceOrchestrator,
        chronicle: AnchorChronicleStore,
    ) -> None:
        self._orchestrator = orchestrator
        self._chronicle = chronicle
        self._turn_index = 0

    @property
    def turn_index(self) -> int:
        return self._turn_index

    @property
    def chronicle(self) -> AnchorChronicleStore:
        return self._chronicle

    def record_turn(
        self,
        session_id: str,
        user_text: str,
        agent_reply: str,
        salience: float = 0.3,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        activated_memory_ids: list[str] | None = None,
        proactive_intent_id: str = "",
    ) -> ExperienceUnit:
        self._turn_index += 1
        unit = ExperienceUnit.make(
            situation=ExperienceSituation(
                session_id=session_id,
                turn_index=self._turn_index,
                perception=user_text,
                narration=agent_reply,
                activated_memory_ids=activated_memory_ids or [],
            ),
            action=ExperienceAction(
                kind=ExperienceActionKind.speaking,
                content=agent_reply,
            ),
            feeling=ExperienceFeeling(
                valence_delta=valence_delta,
                arousal_delta=arousal_delta,
                salience=salience,
                emotion_label=emotion_label,
            ),
            source=ExperienceSource.user.value,
        )
        stamp_anchor_context(unit, AnchorUnitContext(
            direction=InteractionDirection.inbound,
            session_id=session_id,
            proactive_intent_id=proactive_intent_id,
        ))
        self._append_chronicle(unit, user_text, agent_reply)
        self._orchestrator.ingest(unit)
        return unit

    def _append_chronicle(
        self,
        unit: ExperienceUnit,
        user_text: str,
        agent_reply: str,
    ) -> None:
        summary = f"用户：{user_text[:40]}  →  Agent：{agent_reply[:40]}"
        self._chronicle.append(AnchorChronicleEntry(
            kind=AnchorChronicleKind.user_turn,
            summary=summary,
            session_id=unit.situation.session_id,
            turn_index=unit.situation.turn_index,
            emotion_label=unit.feeling.emotion_label,
            salience=unit.feeling.salience,
            experience_id=unit.id,
        ))
