from __future__ import annotations

from typing import Protocol

from ...contracts import RhythmPlan
from ...stage import StageState
from ...stage.on_scene import OnSceneState


class MemoryRecallPort(Protocol):
    """Optional memory recall port for compose."""

    def recall(
        self,
        stage: StageState,
        *,
        on_scene: OnSceneState,
        rhythm: RhythmPlan,
    ) -> str: ...


class JournalPort(Protocol):
    """Optional journal / private note port for compose."""

    def peek(
        self,
        stage: StageState,
        *,
        on_scene: OnSceneState,
        rhythm: RhythmPlan,
    ) -> str: ...


class NullMemoryRecall:
    def recall(
        self,
        stage: StageState,
        *,
        on_scene: OnSceneState,
        rhythm: RhythmPlan,
    ) -> str:
        del stage, on_scene, rhythm
        return ""


class NullJournal:
    def peek(
        self,
        stage: StageState,
        *,
        on_scene: OnSceneState,
        rhythm: RhythmPlan,
    ) -> str:
        del stage, on_scene, rhythm
        return ""
