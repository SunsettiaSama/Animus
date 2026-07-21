from __future__ import annotations

from ...contracts import RhythmPlan, TextGenerator
from ...stage import DesireArc, StageSnapshot, StageState
from ..base import extract_json_object, generate_text
from .affect import refresh_affect, should_refresh_affect
from .arc import DesireArcSupplier, SoftDesireArcSupplier
from .on_scene import should_refresh_on_scene
from .parse import plan_from_payload
from .prompts import RHYTHM_SYSTEM


class RhythmDirector:
    """Rhythm director: init arc + on-scene due check + per-beat gate."""

    name = "rhythm"

    def __init__(
        self,
        llm: TextGenerator | None = None,
        *,
        arc_supplier: DesireArcSupplier | None = None,
        on_scene_every_k: int = 3,
        affect_every_k: int = 2,
    ) -> None:
        if llm is None:
            raise RuntimeError(
                "RhythmDirector requires SoftChannel / LLM; hardcoded gate fallback is forbidden"
            )
        self._llm = llm
        self._arc_supplier = arc_supplier
        self.on_scene_every_k = max(1, int(on_scene_every_k))
        self.affect_every_k = max(1, int(affect_every_k))

    def init(
        self,
        stage: StageState,
        *,
        supplier: DesireArcSupplier | None = None,
        reason: str = "cold_init",
        previous: DesireArc | None = None,
    ) -> DesireArc:
        resolved = supplier or self._arc_supplier
        if resolved is None:
            if self._llm is None:
                raise RuntimeError(
                    "rhythm.init requires SoftDesireArcSupplier(llm) or external DesireArcSupplier"
                )
            resolved = SoftDesireArcSupplier(self._llm)
        del previous
        arc = resolved.build_arc(stage, reason=reason, previous=None)
        stage.set_desire_arc(arc)
        return arc

    def hot_init(
        self,
        stage: StageState,
        *,
        supplier: DesireArcSupplier | None = None,
        reason: str = "hot_init",
    ) -> DesireArc:
        return self.init(stage, supplier=supplier, reason=reason, previous=None)

    def on_scene_due(self, stage: StageState) -> bool:
        return should_refresh_on_scene(stage, every_k=self.on_scene_every_k)

    def affect_due(self, stage: StageState) -> bool:
        return should_refresh_affect(stage, every_k=self.affect_every_k)

    def refresh_affect(
        self,
        stage: StageState,
        *,
        user_text: str,
        trigger: str,
    ) -> tuple[str, str, float]:
        return refresh_affect(
            self._llm,
            stage,
            user_text=user_text,
            trigger=trigger,
        )

    def run(self, snapshot: StageSnapshot) -> RhythmPlan:
        raw = generate_text(
            self._llm,
            system=RHYTHM_SYSTEM,
            user=snapshot.prompt_lines(),
        )
        return plan_from_payload(extract_json_object(raw, director=self.name))
