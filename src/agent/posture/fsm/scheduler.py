from __future__ import annotations

from dataclasses import dataclass, field

from agent.posture.events import InteractionEvent, InteractionEventKind

from .model import TERMINATING_EVENT_KINDS
from .state import PostureFsmState
from .transition.dialogue import DIALOGUE_EVENT_KINDS, apply_dialogue_transition
from .transition.scene import SCENE_EVENT_KINDS, apply_scene_transition


@dataclass
class PostureFsmTransition:
    """单次 FSM 状态转移结果。"""

    before: PostureFsmState
    after: PostureFsmState
    event: InteractionEvent
    notes: list[str] = field(default_factory=list)


def apply_transition(
    state: PostureFsmState,
    event: InteractionEvent,
) -> PostureFsmTransition:
    """总调度：对话期待 / 交织场 / 终止。"""
    before = state.copy()
    after = state.copy()
    notes: list[str] = []

    kind = event.kind

    if kind in DIALOGUE_EVENT_KINDS:
        if kind == InteractionEventKind.turn_closed:
            after.session.turn_index += 1
        dialogue_after, dialogue_notes = apply_dialogue_transition(
            after.dialogue, event
        )
        after.dialogue = dialogue_after
        notes.extend(dialogue_notes)

    elif kind in SCENE_EVENT_KINDS:
        notes.extend(apply_scene_transition(after, event))

    elif kind in TERMINATING_EVENT_KINDS:
        after.reset_idle()
        notes.append(f"terminated via {kind.value}")

    return PostureFsmTransition(before=before, after=after, event=event, notes=notes)
