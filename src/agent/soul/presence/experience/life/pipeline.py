from __future__ import annotations

from typing import TYPE_CHECKING

from config.soul.presence.config import EXPERIENCE_MEMORY_INGEST_THRESHOLD

from ..log import ExperienceLog
from ..orchestrator import ExperienceOrchestrator, MemoryIngestPort
from ..sources import ExperienceSource
from ..unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from .builder import ExperienceBuilder
from agent.soul.presence.transition import PresenceTrigger
from agent.soul.presence.transition.incident.result import IncidentIngestResult

if TYPE_CHECKING:
    from agent.soul.presence.service import PresenceService
    from agent.soul.presence.transition.incident.event import LifeIncident


class LifeExperiencePipeline:
    """生活体验：地标 / 意外 / wander 等 incident → ExperienceUnit → memory。"""

    def __init__(
        self,
        *,
        life_dir: str = "",
        orchestrator: ExperienceOrchestrator | None = None,
        log: ExperienceLog | None = None,
        memory_port: MemoryIngestPort | None = None,
        memory_ingest_threshold: float = EXPERIENCE_MEMORY_INGEST_THRESHOLD,
    ) -> None:
        if orchestrator is None:
            if not life_dir:
                raise ValueError("life_dir is required when orchestrator is omitted")
            self._log = log or ExperienceLog(life_dir)
            self._orchestrator = ExperienceOrchestrator(
                log=self._log,
                memory_port=memory_port,
                memory_ingest_threshold=memory_ingest_threshold,
            )
        else:
            if log is None:
                raise ValueError("log is required when orchestrator is provided")
            self._orchestrator = orchestrator
            self._log = log
        self._builder = ExperienceBuilder(orchestrator=self._orchestrator)

    @property
    def orchestrator(self) -> ExperienceOrchestrator:
        return self._orchestrator

    @property
    def builder(self) -> ExperienceBuilder:
        return self._builder

    @property
    def log(self) -> ExperienceLog:
        return self._log

    def set_memory_port(self, memory_port: MemoryIngestPort | None) -> None:
        self._orchestrator._memory_port = memory_port

    def set_collapser(self, collapser) -> None:
        self._orchestrator.set_collapser(collapser)

    def hot_experiences(self, *, hours: int | None = None) -> list[dict]:
        return [u.to_dict() for u in self._log.recent(hours=hours)]

    def tick(self) -> list[ExperienceUnit]:
        return self._orchestrator.tick()

    def ingest_unit(self, unit: ExperienceUnit) -> None:
        self._orchestrator.ingest(unit)

    def ingest_life_incident(
        self,
        presence: PresenceService,
        incident: LifeIncident,
        *,
        fallback_narration: str = "",
        salience: float = 0.4,
        source: str = ExperienceSource.narrative.value,
    ) -> IncidentIngestResult:
        trigger_result = presence.interface.trigger(PresenceTrigger.incident(incident))
        if trigger_result.outcome.incident is None:
            raise RuntimeError("incident trigger did not produce IncidentIngestResult")
        result = trigger_result.outcome.incident
        if result.applied or fallback_narration.strip() or incident.hint.strip():
            snap = presence.snapshot(incident.session_id)
            perception = snap.state.perception.narrative.strip()
            narration = snap.state.cognition.thinking.strip() or snap.state.affect.narrative.strip()
            if not narration:
                narration = fallback_narration.strip() or incident.hint.strip()
            if not perception:
                perception = incident.hint.strip()

            emotion_label = incident.emotion_text.strip() or snap.state.affect.narrative.strip()[:24]

            unit = ExperienceUnit.make(
                situation=ExperienceSituation(
                    session_id=incident.session_id,
                    perception=perception,
                    narration=narration,
                ),
                action=ExperienceAction(
                    kind=ExperienceActionKind.attending,
                    content=incident.hint.strip() or narration,
                ),
                feeling=ExperienceFeeling(
                    salience=max(salience, incident.salience),
                    emotion_label=emotion_label,
                    valence_delta=incident.emotion_intensity,
                ),
                source=source,
            )
            self._orchestrator.ingest(unit)
        return result
