from __future__ import annotations

from storyview.scene.cards import cards_from_meta
from storyview.types import SceneLocateResult, SceneUnit

_INJECT_HEADER = "【你所处的场景】"


def render_scene_inject(result: SceneLocateResult) -> str:
    body = result.inject_text.strip()
    if not body:
        return ""
    if body.startswith(_INJECT_HEADER):
        return body
    return f"{_INJECT_HEADER}\n{body}"


def build_inject_text(
    scene: SceneUnit | None,
    *,
    transition_text: str = "",
) -> str:
    if scene is None:
        return transition_text.strip()
    parts: list[str] = []
    transition = transition_text.strip()
    narrative = scene.narrative.strip()
    if transition:
        parts.append(transition)
    if narrative:
        parts.append(narrative)
    cards = cards_from_meta(scene.meta)
    if cards:
        card_lines = ["可互动卡片："]
        for card in cards:
            affordances = "、".join(card.affordances) if card.affordances else "（无）"
            conditions = "、".join(card.conditions) if card.conditions else "（无）"
            card_lines.append(
                f"- {card.title}：{card.description}；可互动：{affordances}；使用条件：{conditions}"
            )
        parts.append("\n".join(card_lines))
    return "\n".join(parts)
