from __future__ import annotations

from dataclasses import dataclass, field

from .guidance.layer import SpeakGuidanceLayer
from .persona import SpeakPersonaLayer
from .scene import SpeakSceneLayer
from .system.layer import SpeakSystemLayer
from .system.reply_style import SpeakReplyStyle
from .system.role import SpeakTurnMode


@dataclass
class PreparedComposeFrame:
    """后台预组装的 prompt 帧（不含本轮 user_text）。"""

    session_id: str
    mode: SpeakTurnMode
    generation: int
    system: SpeakSystemLayer
    persona: SpeakPersonaLayer
    scene: SpeakSceneLayer
    guidance: SpeakGuidanceLayer
    wants_share: bool = False
    share_summary: str = ""
    notes: list[str] = field(default_factory=list)
    reply_style: SpeakReplyStyle = field(default_factory=SpeakReplyStyle)
