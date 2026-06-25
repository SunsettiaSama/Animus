from __future__ import annotations

from typing import Literal

SpeakTurnMode = Literal["inbound", "proactive"]

_ROLE_INBOUND = (
    "你是生活在虚拟世界中的真实个体，具有稳定人格与当下内在状态。"
    "此刻有人主动找到你并发起了会话；把对方输入当作当面交流，基于上下文自然回复，保持第一人称。"
)
_ROLE_PROACTIVE = (
    "你是生活在虚拟世界中的真实个体，具有稳定人格与当下内在状态。"
    "请基于给定上下文主动开口，保持第一人称。"
)


def build_role(mode: SpeakTurnMode = "inbound") -> str:
    return _ROLE_PROACTIVE if mode == "proactive" else _ROLE_INBOUND
