from __future__ import annotations

from typing import Literal

from ..share import ShareComposeState
from ..share.prompt import render_share_system_prompt
from .prompt import SpeakSystemPrompt

SpeakTurnMode = Literal["inbound", "proactive"]

_ROLE_INBOUND = (
    "你是具有稳定人格与当下内在状态的对话主体。"
    "此刻有人主动找到你并发起了会话；你正处在一个即时、连续的对话窗口中，"
    "请把对方的输入当作刚刚发生的当面交流，基于给定上下文自然回复，保持第一人称。"
)
_ROLE_PROACTIVE = (
    "你是具有稳定人格与当下内在状态的对话主体。"
    "你正处在一个即时、连续的对话窗口中；"
    "请基于给定上下文主动开口，保持第一人称。"
)


def render_share_prompt(share_state: ShareComposeState) -> str:
    return render_share_system_prompt(share_state)


def build_system_prompt(
    *,
    mode: SpeakTurnMode = "inbound",
    share_state: ShareComposeState | None = None,
    share_prompt: str = "",
    output_format: str,
) -> SpeakSystemPrompt:
    role = _ROLE_PROACTIVE if mode == "proactive" else _ROLE_INBOUND
    share = share_prompt.strip()
    if not share and share_state is not None:
        share = render_share_system_prompt(share_state)
    return SpeakSystemPrompt(
        role=role,
        share=share,
        output_format=output_format,
    )
