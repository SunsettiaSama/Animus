from __future__ import annotations

from dataclasses import dataclass, field

from agent.interaction.kinds import InteractionModalityKind

from .events import InteractionEvent
from .fsm.scheduler import apply_transition
from .fsm.state import PostureFsmState
from .snapshot import InteractionPostureSnapshot


@dataclass
class PostureTransitionResult:
    """单次姿态调整结果（含 session 级快照）。"""

    before: InteractionPostureSnapshot
    after: InteractionPostureSnapshot
    event: InteractionEvent
    notes: list[str] = field(default_factory=list)


class InteractionPosture:
    """Agent 交互姿态层：session 全程持有对话/场景结构状态。"""

    def __init__(self) -> None:
        self._sessions: dict[str, InteractionPostureSnapshot] = {}

    def snapshot(self, session_id: str) -> InteractionPostureSnapshot:
        if session_id not in self._sessions:
            self._sessions[session_id] = InteractionPostureSnapshot(
                session_id=session_id,
                state=PostureFsmState.empty(),
            )
        return self._sessions[session_id]

    def dispatch(self, event: InteractionEvent) -> PostureTransitionResult:
        sid = event.session_id
        before = self._copy(sid)
        fsm_result = apply_transition(before.state, event)
        after = self._copy(sid)
        after.apply_fsm_state(fsm_result.after)
        self._sessions[sid] = after
        return PostureTransitionResult(
            before=before,
            after=after,
            event=event,
            notes=list(fsm_result.notes),
        )

    def bind_interaction(
        self,
        session_id: str,
        interaction_id: str,
        *,
        stakes: str = "",
        channel: str = "",
        modality: str = InteractionModalityKind.dialogue.value,
    ) -> InteractionPostureSnapshot:
        snap = self._copy(session_id)
        snap.state.dialogue.line_open = True
        snap.state.session.interaction_id = interaction_id
        if stakes:
            snap.state.scene.stakes = stakes
        if channel:
            snap.state.session.channel = channel
        if modality:
            snap.state.session.primary_modality = modality
        self._sessions[session_id] = snap
        return snap

    def _copy(self, session_id: str) -> InteractionPostureSnapshot:
        cur = self.snapshot(session_id)
        return InteractionPostureSnapshot(
            session_id=cur.session_id,
            state=cur.state.copy(),
            meta=dict(cur.meta),
        )


DialoguePosture = InteractionPosture
