from __future__ import annotations

from typing import TYPE_CHECKING

from config.soul.presence.config import EXPERIENCE_MEMORY_INGEST_THRESHOLD

from ..dialogue import DialogueExperiencePipeline
from ..domain import ExperienceSource, ExperienceUnit
from ..ingest import IncidentIngestResult, LifeExperiencePipeline, LifeIncident
from ..unit_layer import ExperienceUnitLayer
from ..unit_layer.manage.collapser import ExperienceCollapser
from ..unit_layer.promote.ports import MemoryIngestPort

if TYPE_CHECKING:
    from agent.soul.life.anchor.chronicle import AnchorChronicleStore
    from agent.soul.life.virtual.chronicle import VirtualChronicleStore
    from agent.soul.presence.service import PresenceService


class LifeExperienceStack:
    """共享编排器 + 对话/生活两个子模块；与 Presence 双向直连。"""

    def __init__(
        self,
        life_dir: str,
        *,
        memory_port: MemoryIngestPort | None = None,
        anchor_chronicle: AnchorChronicleStore | None = None,
        virtual_chronicle: VirtualChronicleStore | None = None,
        collapser: ExperienceCollapser | None = None,
        memory_ingest_threshold: float = EXPERIENCE_MEMORY_INGEST_THRESHOLD,
    ) -> None:
        self.units = ExperienceUnitLayer(
            life_dir,
            memory_port=memory_port,
            anchor_chronicle=anchor_chronicle,
            virtual_chronicle=virtual_chronicle,
            collapser=collapser,
            memory_ingest_threshold=memory_ingest_threshold,
        )
        self.log = self.units.log
        self.orchestrator = self.units.manage
        self.dialogue = DialogueExperiencePipeline(orchestrator=self.orchestrator)
        self.life = LifeExperiencePipeline(
            orchestrator=self.orchestrator,
            log=self.log,
        )
        self._presence: PresenceService | None = None

    def bind_presence(self, presence: PresenceService) -> None:
        """Life ↔ Presence 双向绑定：对话直写 + unit ingest 后自动 sync。"""
        self._presence = presence
        self.dialogue.bind_presence(presence)
        self.life.bind_presence(presence)
        presence.bind_life_experience(self)
        self.orchestrator.set_after_ingest(self._sync_presence_after_unit)

    @property
    def presence(self) -> PresenceService | None:
        return self._presence

    def _require_presence(self) -> PresenceService:
        if self._presence is None:
            raise RuntimeError("LifeExperienceStack 未 bind_presence")
        return self._presence

    def _sync_presence_after_unit(self, unit: ExperienceUnit) -> None:
        if unit.source == "collision":
            return
        session_id = unit.situation.session_id or "tao"
        self._presence.on_unit_ingested(unit, self.log)
        self._presence.pull_and_sync_from_life(self.log, session_id)

    def sync_presence(
        self,
        session_id: str = "tao",
        *,
        hot_hours: float | None = 2,
        tail: int = 12,
    ) -> dict[str, object]:
        return self._require_presence().pull_and_sync_from_life(
            self.log,
            session_id,
            hours=hot_hours,
            tail=tail,
        )

    def ingest_incident(
        self,
        incident: LifeIncident,
        *,
        fallback_narration: str = "",
        salience: float = 0.4,
        source: str | None = None,
    ) -> IncidentIngestResult:
        if source is None:
            source = ExperienceSource.narrative.value
            if incident.kind.value == "surprise":
                source = ExperienceSource.surprise.value
        return self.life.ingest_life_incident(
            self._require_presence(),
            incident,
            fallback_narration=fallback_narration or incident.hint,
            salience=salience,
            source=source,
        )

    def record_dialogue_turn(
        self,
        *,
        session_id: str,
        user_text: str,
        agent_text: str,
        salience: float = 0.3,
        salience_note: str = "",
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        activated_memory_ids: list[str] | None = None,
        proactive_intent_id: str = "",
    ) -> None:
        self.dialogue.record_dialogue_turn(
            self._require_presence(),
            session_id=session_id,
            user_text=user_text,
            agent_text=agent_text,
            salience=salience,
            salience_note=salience_note,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            activated_memory_ids=activated_memory_ids,
            proactive_intent_id=proactive_intent_id,
        )

    def close_dialogue(self, session_id: str = "tao") -> ExperienceUnit | None:
        return self.dialogue.close_dialogue(self._require_presence(), session_id)

    def ingest_compression_block(
        self,
        block,
        *,
        interactor_id: str = "",
        llm=None,
        agent_persona_narrative: str = "",
    ) -> None:
        """Speak 蒸馏块 → Skill1 编写 ExperienceUnit → 热日志 + 立即 Memory 擢升。"""
        from agent.soul.life.experience.skills import create_unit_from_compression

        if llm is None:
            raise RuntimeError("ingest_compression_block 需要 LLM（体验编写 Skill1）")
        result = create_unit_from_compression(
            llm,
            block,
            interactor_id=interactor_id,
            agent_persona_narrative=agent_persona_narrative,
        )
        self.orchestrator.ingest_authored_unit(result.unit)

