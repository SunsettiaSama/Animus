from __future__ import annotations

from ..orchestrator.state.core.types import SessionSnapshot
from .base import DirectorOutput


class SocialArmDirector:
    name = "social_arm"

    def run(
        self,
        snapshot: SessionSnapshot,
        *,
        silence_armed: bool = False,
        social_armed: str | None = None,
    ) -> DirectorOutput:
        return DirectorOutput(
            director=self.name,
            payload={
                "social_armed": social_armed,
                "silence_armed": silence_armed,
                "turn_index": snapshot.signals.turn_index,
            },
            reason="social_snapshot",
        )


class InterruptDirector:
    name = "interrupt"

    def run(self, snapshot: SessionSnapshot) -> DirectorOutput:
        reorder = False
        cancel_unsent = False
        if snapshot.runtime.push_phase == "pushing":
            reorder = snapshot.runtime.current_segment_index < snapshot.runtime.segment_total
            cancel_unsent = reorder
        return DirectorOutput(
            director=self.name,
            payload={
                "reorder": reorder,
                "cancel_unsent": cancel_unsent,
                "force_reply": False,
            },
            reason="interrupt_async",
        )
