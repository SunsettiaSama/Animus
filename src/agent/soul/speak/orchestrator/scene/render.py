from __future__ import annotations

_WORLD_HEADER = "【你所处的世界】"


def render_world_scene_block(text: str) -> str:
    body = text.strip()
    if not body:
        return ""
    if body.startswith(_WORLD_HEADER) or body.startswith("【你所处的场景】"):
        return body
    return f"{_WORLD_HEADER}\n{body}"
