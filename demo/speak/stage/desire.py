from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ArcSource = Literal["rhythm.init", "soul.presence", "soul.life", "external"]

__all__ = ["DesireArc", "ArcSource"]


@dataclass(frozen=True)
class DesireArc:
    """
    本轮对话弧快照：自然语言基调。

    init 时拟定，贯穿整段交互，供开口指令中枢阅读；不含数值峰值。
    """

    text: str
    source: ArcSource = "rhythm.init"

    def snapshot(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
        }

    def one_line(self) -> str:
        body = self.text.replace("\n", " ").strip()
        if not body:
            return "(empty arc)"
        return body if len(body) <= 160 else body[:157] + "…"
