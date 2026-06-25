from __future__ import annotations

import re

from ...director.types import MemoryInjectPlan

_SHORT_ACK_RE = re.compile(
    r"^(嗯|哦|啊|好|好的|行|可以|ok|OK|嗯嗯|对对|是的|是|对|哈|哈哈|嗯。)$",
    re.IGNORECASE,
)


def is_short_ack(user_text: str) -> bool:
    text = user_text.strip()
    if not text:
        return False
    if len(text) <= 4 and _SHORT_ACK_RE.match(text):
        return True
    return len(text) <= 2


def has_topic_shift_signal(user_text: str) -> bool:
    text = user_text.strip()
    if len(text) >= 12:
        return True
    if re.search(r"[\u4e00-\u9fff]{4,}", text):
        return True
    if "?" in text or "？" in text:
        return True
    return False


def build_memory_inject_plan(
    *,
    user_text: str,
    cold_start: bool,
    arc_continues: bool,
) -> MemoryInjectPlan:
    if cold_start:
        return MemoryInjectPlan(
            request_emergence=True,
            request_keyword=True,
            request_portrait=True,
            include_recall=True,
            include_portrait=True,
        )
    if is_short_ack(user_text):
        return MemoryInjectPlan(
            request_emergence=False,
            request_keyword=False,
            request_portrait=False,
            include_recall=False,
            include_portrait=True,
        )
    if arc_continues and not has_topic_shift_signal(user_text):
        return MemoryInjectPlan(
            request_emergence=False,
            request_keyword=True,
            request_portrait=False,
            include_recall=True,
            include_portrait=False,
        )
    return MemoryInjectPlan(
        request_emergence=True,
        request_keyword=True,
        request_portrait=True,
        include_recall=True,
        include_portrait=True,
    )
