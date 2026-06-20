from __future__ import annotations

from ..state.core.types import SessionSnapshot
from .base import DirectorOutput


class MemoryInjectDirector:
    name = "memory_inject"

    def run(self, snapshot: SessionSnapshot, *, user_text: str = "") -> DirectorOutput:
        text = user_text.strip() or snapshot.dialogue.user_text.strip()
        request_emergence = len(text) >= 12
        request_keyword = "?" in text or "吗" in text
        return DirectorOutput(
            director=self.name,
            payload={
                "request_emergence": request_emergence,
                "request_keyword": request_keyword,
                "request_portrait": snapshot.signals.turn_index % 3 == 0,
                "include_recall": True,
                "include_portrait": True,
            },
            reason="memory_heuristic",
        )


class ShareImpulseDirector:
    name = "share_impulse"

    def run(self, snapshot: SessionSnapshot, *, share_wants: bool = False) -> DirectorOutput:
        return DirectorOutput(
            director=self.name,
            payload={
                "include_preview": share_wants,
                "include_in_planner": share_wants,
                "share_queue_count": int(
                    snapshot.orchestrator.compose_meta.get("share_queue_count", 0),
                ),
            },
            reason="share_state",
        )


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
