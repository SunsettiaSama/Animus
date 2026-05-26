from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeakInjectedContext:
    """外部注入的结构化上下文（persona / presence / 用户输入）。"""

    persona_traits: str = ""
    self_concept: str = ""
    presence_static: str = ""
    user_text: str = ""
