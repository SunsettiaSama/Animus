from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .virtual.layer import VirtualLayer


class NarrativePurpose(str, Enum):
  compose = "compose"
  fill = "fill"
  surprise = "surprise"
  fabricate = "fabricate"


def format_continuity(lines: list[str]) -> str:
    if not lines:
        return "（无相关记忆，可自由发挥）"
    return "\n".join(f"- {line}" for line in lines)


def format_landmark_intents(intents: list[str]) -> str:
    if not intents:
        return "（暂无）"
    return "\n".join(f"- {line}" for line in intents)


class NarrativeContextSupplier(Protocol):
    """按叙事任务刷新 persona 与记忆连续性。"""

    def refresh(
        self,
        layer: VirtualLayer,
        purpose: NarrativePurpose,
        *,
        query: str = "",
    ) -> None: ...
