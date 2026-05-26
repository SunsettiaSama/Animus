from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeakSystemPrompt:
    """内部构造的结构化系统提示词。"""

    role: str = ""
    share: str = ""
    output_format: str = ""

    def render(self) -> str:
        parts: list[str] = []
        for block in (self.role, self.share, self.output_format):
            text = block.strip()
            if text:
                parts.append(text)
        return "\n\n".join(parts)
