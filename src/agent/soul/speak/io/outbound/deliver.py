from __future__ import annotations

from dataclasses import dataclass, field

from .unit import SpeakAnswer


@dataclass
class SpeakDeliverResult:
    """对外说话交付结果。"""

    answer: SpeakAnswer
    notes: list[str] = field(default_factory=list)


def deliver_text(
    session_id: str,
    text: str,
    *,
    final: bool = True,
) -> SpeakDeliverResult:
    """出站：构造对外 answer（尚未推送 UI）。"""
    return SpeakDeliverResult(answer=SpeakAnswer(text=text, final=final))
