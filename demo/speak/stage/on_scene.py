from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# present=盯着对话；drift=走神；notice=注意到别的事
OnSceneFocus = Literal["present", "drift", "notice"]


@dataclass
class OnSceneState:
    """
    临场状态：最近态的短衍生（1～2 句），由 rhythm 单独轮询刷新。

    不进会话噪声；交给 compose 决定本拍组装哪些可选块。
    """

    text: str = ""
    focus: OnSceneFocus = "present"
    beat_index: int = 0

    @property
    def ready(self) -> bool:
        return bool(self.text.strip())

    def one_line(self, *, limit: int = 80) -> str:
        body = " ".join(self.text.strip().split())
        if len(body) > limit:
            body = body[: limit - 1] + "…"
        return body

    def snapshot(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "focus": self.focus,
            "beat_index": self.beat_index,
        }
