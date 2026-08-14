from __future__ import annotations

_LEGACY_SCENE_PREFIXES = (
    "【你所处的场景】",
    "【你所处的世界】",
)


def _strip_legacy_scene_header(text: str) -> str:
    body = text.strip()
    for prefix in _LEGACY_SCENE_PREFIXES:
        if body.startswith(prefix):
            return body[len(prefix):].strip()
    return body


def render_world_scene_block(text: str) -> str:
    body = _strip_legacy_scene_header(text)
    if not body:
        return ""
    if body.startswith("你"):
        return body
    return f"你此刻身处{body.rstrip('。')}。"


def normalize_scene_inject(text: str) -> str:
    """storyview 注入 → 主 prompt 软边界场景句。"""
    return render_world_scene_block(text)
