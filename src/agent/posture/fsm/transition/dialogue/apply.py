from __future__ import annotations

from agent.posture.events import InteractionEvent, InteractionEventKind

from ...state.dialogue import DialogueStance

DIALOGUE_EVENT_KINDS = frozenset(
    {
        InteractionEventKind.user_text,
        InteractionEventKind.agent_utterance,
        InteractionEventKind.proactive_open,
        InteractionEventKind.proactive_delivered,
        InteractionEventKind.ambiguity_detected,
        InteractionEventKind.turn_closed,
    }
)


def _payload_intent_id(payload: dict) -> str:
    return str(payload.get("intent_id", ""))


def apply_dialogue_transition(
    dialogue: DialogueStance,
    event: InteractionEvent,
) -> tuple[DialogueStance, list[str]]:
    """更新对话结构状态（开线 / 主动意图），不迁移期待。"""
    before = dialogue.copy()
    after = dialogue.copy()
    notes: list[str] = []
    kind = event.kind
    payload = event.payload

    if kind == InteractionEventKind.user_text:
        if not before.line_open:
            after.line_open = True
            notes.append("line opened")

    elif kind == InteractionEventKind.agent_utterance:
        if not before.line_open:
            after.line_open = True
            notes.append("line opened")

    elif kind in (
        InteractionEventKind.proactive_open,
        InteractionEventKind.proactive_delivered,
    ):
        after.line_open = True
        intent_id = _payload_intent_id(payload)
        if intent_id:
            after.proactive_intent_id = intent_id
        elif (
            kind == InteractionEventKind.proactive_delivered
            and before.proactive_intent_id
        ):
            after.proactive_intent_id = before.proactive_intent_id
        notes.append(kind.value)

    elif kind == InteractionEventKind.ambiguity_detected:
        if not before.line_open:
            after.line_open = True
            notes.append("line opened")
        notes.append("ambiguity_detected")

    elif kind == InteractionEventKind.turn_closed:
        notes.append("turn_closed")

    if not notes:
        notes.append(f"dialogue: noop for {kind.value}")

    return after, notes
