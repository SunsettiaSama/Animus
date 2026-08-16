from __future__ import annotations

from ..orchestrator.state.core.presence_card import CharacterPresenceCard
from .base import DirectorOutput


def apply_presence_card_output(
    state,
    output: DirectorOutput,
    *,
    turn_index: int = 0,
) -> CharacterPresenceCard | None:
    """将编剧/回退产出写入 state.presence_card。"""
    payload = dict(output.payload or {})
    payload["turn_index"] = turn_index or int(payload.get("turn_index") or 0)
    card = CharacterPresenceCard.from_dict(payload)
    if card is None:
        return None
    state.presence_card = card
    return card
