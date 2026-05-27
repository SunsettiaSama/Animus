from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeakStatusInjected:
    """状态层外部注入：随事件与对话演进，由 inbound compose 交给 compose。"""

    presence: str = ""
    dialogue_compressed: str = ""

    def render_blocks(self) -> list[str]:
        return [
            block.strip()
            for block in (self.presence, self.dialogue_compressed)
            if block.strip()
        ]
