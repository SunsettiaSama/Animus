from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infra.llm import BaseLLM


def parse_continuity_verdict_line(raw: str) -> tuple[str, str]:
    """解析连续性裁决首行 ``CONTINUE`` / ``BREAK``。"""
    lines = [ln.strip() for ln in (raw or "").strip().splitlines() if ln.strip()]
    if not lines:
        return "", ""
    head = lines[0].upper()
    reason = ""
    for ln in lines[1:]:
        low = ln.lower()
        if low.startswith("reason:"):
            reason = ln.split(":", 1)[-1].strip()
            break
    if head in ("CONTINUE", "BREAK"):
        return head, reason
    if "BREAK" in head:
        return "BREAK", reason or head
    if "CONTINUE" in head:
        return "CONTINUE", reason or head
    return "", reason


class InfraContinuityLlmHandler:
    """``infra.llm.BaseLLM`` → :class:`ContinuityLlmHandler`。"""

    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def complete(self, system: str, user: str) -> str:
        from infra.llm import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system),
            HumanMessage(content=user),
        ]
        return self._llm.generate_messages(messages).strip()
