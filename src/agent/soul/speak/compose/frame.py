from __future__ import annotations

from dataclasses import dataclass, field

from .injected.persona import SpeakPersonaInjected
from agent.soul.speak.io.inbound.compose import SpeakStatusInjected
from .reply_style import SpeakReplyStyle
from .system import SpeakSystemPrompt
from .bundle import SpeakTurnMode


@dataclass
class PreparedComposeFrame:
    """后台线程预组装的 compose 帧（不含本轮 user_text）。"""

    session_id: str
    mode: SpeakTurnMode
    generation: int
    persona: SpeakPersonaInjected
    status: SpeakStatusInjected
    system: SpeakSystemPrompt
    wants_share: bool = False
    share_summary: str = ""
    notes: list[str] = field(default_factory=list)
    reply_style: SpeakReplyStyle = field(default_factory=SpeakReplyStyle)
