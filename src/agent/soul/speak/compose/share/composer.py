from __future__ import annotations

from dataclasses import dataclass, field

from config.soul.presence.config import PROACTIVE_OPEN_THRESHOLD

from .prompt import render_share_system_prompt
from .handoff import pop_share_handoff
from .reveal import ShareRevealGate, ShareRevealResult
from .state import ShareComposeState, collect_share_state


@dataclass
class ShareDriveEvaluation:
    """内驱/主动 speak 评估（保留阈值逻辑，供 drive 使用）。"""

    should_speak: bool
    state: ShareComposeState
    toward_user: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return self.state.summary

    @property
    def package(self):
        return self.state.package


class ShareDesireComposer:
    """分享意愿模块：维护待分享事件、拼接摘要、生成 system 提示、揭示接口。"""

    def __init__(
        self,
        *,
        proactive_threshold: float = PROACTIVE_OPEN_THRESHOLD,
        reveal_gate: ShareRevealGate | None = None,
    ) -> None:
        self._threshold = proactive_threshold
        self.reveal_gate = reveal_gate or ShareRevealGate()

    def collect(self, presence_snap) -> ShareComposeState:
        return collect_share_state(presence_snap)

    def render_system_prompt(self, state: ShareComposeState) -> str:
        return render_share_system_prompt(state)

    def evaluate_drive(self, presence_snap) -> ShareDriveEvaluation:
        state = self.collect(presence_snap)
        toward_user = float(getattr(presence_snap.state.expectation, "toward_user", 0.0))
        notes: list[str] = []

        if not state.wants_share:
            notes.append("no share desire")
            return ShareDriveEvaluation(
                should_speak=False,
                state=state,
                toward_user=toward_user,
                notes=notes,
            )

        impulse_level = float(getattr(presence_snap.interaction, "impulse_level", 0.0))
        should_speak = toward_user >= self._threshold or impulse_level >= 0.35
        if should_speak:
            notes.append("share desire ready for proactive speak")
        else:
            notes.append(
                f"share desire present, accumulating (toward_user={toward_user:.2f})"
            )
        return ShareDriveEvaluation(
            should_speak=should_speak,
            state=state,
            toward_user=toward_user,
            notes=notes,
        )

    def reveal(
        self,
        presence_snap,
        pointer: str,
        *,
        trigger_source: str = "",
    ) -> ShareRevealResult:
        state = self.collect(presence_snap)
        return self.reveal_gate.trigger(
            state=state,
            pointer=pointer,
            source=trigger_source,
        )

    def pop_handoff(
        self,
        presence,
        session_id: str,
    ) -> ShareRevealResult:
        return pop_share_handoff(presence, session_id)
