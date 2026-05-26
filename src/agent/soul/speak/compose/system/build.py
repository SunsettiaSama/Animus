from __future__ import annotations

from typing import Literal

from ..share_queue import SharePromptHint
from .prompt import SpeakSystemPrompt

SpeakTurnMode = Literal["inbound", "proactive"]

_ROLE_INBOUND = (
    "你是具有稳定人格与当下内在状态的对话主体。"
    "请基于给定上下文自然回复用户，保持第一人称。"
)
_ROLE_PROACTIVE = (
    "你是具有稳定人格与当下内在状态的对话主体。"
    "请基于给定上下文主动开口，保持第一人称。"
)


def render_share_prompt(share_hint: SharePromptHint) -> str:
    if not share_hint.wants_share:
        return ""
    lines = ["你有想要分享的内容。"]
    summary = share_hint.summary.strip()
    if summary:
        lines.append(f"分享摘要：{summary}")
    return "\n".join(lines)


def build_system_prompt(
    *,
    mode: SpeakTurnMode = "inbound",
    share_hint: SharePromptHint,
    output_format: str,
) -> SpeakSystemPrompt:
    role = _ROLE_PROACTIVE if mode == "proactive" else _ROLE_INBOUND
    return SpeakSystemPrompt(
        role=role,
        share=render_share_prompt(share_hint),
        output_format=output_format,
    )
