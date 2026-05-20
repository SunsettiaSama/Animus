from __future__ import annotations

from agent.posture.events import InteractionEvent, InteractionEventKind

from ...state import PostureFsmState

SCENE_EVENT_KINDS = frozenset(
    {
        InteractionEventKind.scene_enter,
        InteractionEventKind.scene_leave,
    }
)


def apply_scene_transition(
    state: PostureFsmState,
    event: InteractionEvent,
) -> list[str]:
    """交织场结构转移。"""
    notes: list[str] = []
    p = event.payload
    scene = state.scene
    dialogue = state.dialogue

    if event.kind == InteractionEventKind.scene_enter:
        line_was_closed = not dialogue.line_open
        admitted = bool(p.get("admitted", True))
        scene.in_scene = True
        scene.scene_admitted = admitted
        scene.scene_id = str(p.get("scene_id", ""))
        scene.scene_kind = str(p.get("scene_kind", ""))
        scene.scene_title = str(p.get("title", ""))
        if str(p.get("stakes", "")):
            scene.stakes = str(p["stakes"])
        if line_was_closed:
            dialogue.line_open = True
        notes.append(
            "scene_enter" + (" admitted" if admitted else " pending admission")
        )

    elif event.kind == InteractionEventKind.scene_leave:
        scene.reset()
        notes.append("scene_leave")

    return notes
