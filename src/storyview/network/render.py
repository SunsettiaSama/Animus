from __future__ import annotations

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
    return "\n".join(parts)
