from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

UtteranceHoldPreset = Literal[3000, 5000]


@dataclass
class SessionUtterancePacing:
    """用户发消息后是否额外等待，以便连续输入说完。"""

    enabled: bool = False
    hold_ms: UtteranceHoldPreset = 3000

    def snapshot(self) -> dict[str, object]:
        return {"enabled": self.enabled, "hold_ms": self.hold_ms}
