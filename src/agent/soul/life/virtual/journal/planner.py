from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .contracts import (
    LandmarkAgendaDraftResult,
    LandmarkAgendaPreviewResult,
    LandmarkPlanningResult,
    LandmarkPlanningStrategy,
    LegacyLandmarkComposeResult,
)
from .agenda.cue import build_landmark_agenda_public_cue
from .agenda.planner import LandmarkAgendaPlanner
from .agenda.store import LandmarkAgendaStore
from .agenda.tools import (
    AgendaToolBundle,
    LifeJournalLookupAdapter,
    StorySceneGroundingPort,
    VirtualChronicleLookupAdapter,
)

if TYPE_CHECKING:
    from ..layer import VirtualLayer


class _ContinuityMemoryRecallAdapter:
    def __init__(self, virtual: VirtualLayer) -> None:
        self._virtual = virtual

    def recall(self, query: str) -> list[str]:
        from ...narrative_context import NarrativePurpose

        self._virtual.ensure_narrative_context(
            NarrativePurpose.compose,
            query=query.strip() or "明天行动议程",
        )
        return list(self._virtual.continuity_memories)


class _StorySceneGroundingAdapter(StorySceneGroundingPort):
    def __init__(self, virtual: VirtualLayer) -> None:
        self._virtual = virtual

    def ground_scene_for_cue(self, cue: str, *, policy=None):
        from storyview.types import SceneGroundingPolicy

        port = self._virtual._require_story_port()
        resolved_policy = (
            policy
            if isinstance(policy, SceneGroundingPolicy)
            else self._virtual.scene_grounding_policy
        )
        return port.ground_scene_for_cue(
            self._virtual.world_id,
            cue,
            policy=resolved_policy,
        )


class JournalPlanner:
    """按 strategy 调度 legacy landmark 或 LandmarkAgenda 旁路。"""

    def __init__(
        self,
        virtual: VirtualLayer,
        agenda_store: LandmarkAgendaStore,
        *,
        hot_experience_supplier: Callable[..., list] | None = None,
    ) -> None:
        self._virtual = virtual
        self._agenda_store = agenda_store
        self._hot_experience_supplier = hot_experience_supplier

    def compose(
        self,
        strategy: LandmarkPlanningStrategy = LandmarkPlanningStrategy.legacy,
        *,
        target_date: str | None = None,
        save: bool = True,
    ) -> LandmarkPlanningResult:
        if strategy == LandmarkPlanningStrategy.legacy:
            raw = self._virtual.compose_landmark()
            if raw is None:
                return None
            return LegacyLandmarkComposeResult(
                intention=str(raw.get("intention", "")).strip(),
                context=str(raw.get("context", "")).strip(),
            )

        if strategy == LandmarkPlanningStrategy.agenda_draft:
            result = self._compose_agenda_draft(target_date=target_date)
            if save:
                self._agenda_store.append(result.agenda)
            return result

        if strategy == LandmarkPlanningStrategy.agenda_story_preview:
            draft = self._compose_agenda_draft(target_date=target_date)
            if save:
                self._agenda_store.append(draft.agenda)
            preview = self._virtual.preview_landmark_agenda_story(draft.agenda)
            return LandmarkAgendaPreviewResult(
                agenda=preview.agenda,
                public_cue=preview.public_cue,
                question=preview.question,
                answer=preview.answer,
                revision_trace=list(draft.revision_trace),
            )

        raise ValueError(f"unsupported landmark planning strategy: {strategy}")

    def latest_agendas(self, *, limit: int = 10):
        return self._agenda_store.latest(limit=limit)

    def save_agenda(self, agenda) -> None:
        self._agenda_store.upsert(agenda)

    def compose_draft(
        self,
        *,
        target_date: str | None = None,
    ) -> LandmarkAgendaDraftResult:
        return self._compose_agenda_draft(target_date=target_date)

    def _compose_agenda_draft(
        self,
        *,
        target_date: str | None = None,
    ) -> LandmarkAgendaDraftResult:
        planner = self._build_agenda_planner()
        return planner.compose_tomorrow_agenda(
            profile_narrative=self._virtual.profile_narrative,
            world_background=self._virtual.world_background,
            target_date=target_date,
            recent_landmark_intents=self._virtual.journal.recent_done_intent_lines(3),
        )

    def _build_agenda_planner(self) -> LandmarkAgendaPlanner:
        llm = self._virtual.require_llm()
        from .agenda.tools import LifeJournalLookupAdapter, VirtualChronicleLookupAdapter

        tools = AgendaToolBundle(
            memory=_ContinuityMemoryRecallAdapter(self._virtual),
            journal=LifeJournalLookupAdapter(self._virtual.journal),
            chronicle=VirtualChronicleLookupAdapter(
                self._virtual.chronicle,
                hot_supplier=self._hot_experience_supplier,
            ),
            scene_grounding=_StorySceneGroundingAdapter(self._virtual),
        )
        return LandmarkAgendaPlanner(llm, tools)

    def build_public_cue(self, agenda) -> str:
        return build_landmark_agenda_public_cue(agenda)
