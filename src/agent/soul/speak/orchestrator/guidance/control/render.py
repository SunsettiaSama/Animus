from __future__ import annotations

from .state import GuidanceControlState


def render_control_arc(state: GuidanceControlState) -> str:
    body = state.narrative.strip()
    if not body:
        return ""
    if not (body.startswith('"') or body.startswith('"')):
        body = f'"{body}"'
    return f"【对话引导】\n{body}"
