from __future__ import annotations

from dataclasses import dataclass, field

from .persona import SpeakPersonaInjected
from agent.soul.speak.io.inbound.compose.block import SpeakStatusInjected


@dataclass
class SpeakInjectedContext:
    """Speak 外部注入上下文。

    - persona：人格层，compose 周期内视为稳定
    - status：状态层，每轮随事件重新采集
    - user_text：本轮用户输入（HumanMessage 侧，不进 system）
    """

    persona: SpeakPersonaInjected = field(default_factory=SpeakPersonaInjected)
    status: SpeakStatusInjected = field(default_factory=SpeakStatusInjected)
    user_text: str = ""

    def render_system_blocks(self) -> list[str]:
        blocks: list[str] = []
        blocks.extend(self.persona.render_blocks())
        blocks.extend(self.status.render_blocks())
        return blocks
