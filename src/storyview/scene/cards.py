from __future__ import annotations

from storyview.types import SceneCard, SceneUnit


def cards_from_meta(meta: dict | None) -> list[SceneCard]:
    if not meta:
        return []
    raw = meta.get("cards") or []
    if not isinstance(raw, list):
        return []
    return [
        SceneCard.from_dict(item)
        for item in raw
        if isinstance(item, dict) and SceneCard.from_dict(item).title
    ]


def cards_to_meta(cards: list[SceneCard]) -> dict:
    return {"cards": [card.to_dict() for card in cards]}


def scene_cards(scene: SceneUnit) -> list[SceneCard]:
    return cards_from_meta(scene.meta)
