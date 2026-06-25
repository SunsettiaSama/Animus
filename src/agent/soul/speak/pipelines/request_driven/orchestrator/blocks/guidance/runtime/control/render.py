from __future__ import annotations

from .state import GuidanceControlState


def render_control_arc(state: GuidanceControlState) -> str:
    """对话引导：直接输出 narrative 自然段，不加硬边界标题。"""
    return state.narrative.strip()
