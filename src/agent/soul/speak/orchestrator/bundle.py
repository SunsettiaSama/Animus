from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .guidance.layer import SpeakGuidanceLayer
from .persona import SpeakPersonaLayer
from .scene import SpeakSceneLayer
from .system.layer import SpeakSystemLayer
from .system.reply_style import SpeakReplyStyle
from .system.role import SpeakTurnMode

__all__ = ["SpeakPromptBundle", "SpeakTurnMode"]


@dataclass
class SpeakPromptBundle:
    """Speak 一轮 prompt：system / persona / scene / guidance 四层 + user。"""

    session_id: str
    mode: SpeakTurnMode = "inbound"
    system: SpeakSystemLayer = field(default_factory=SpeakSystemLayer)
    persona: SpeakPersonaLayer = field(default_factory=SpeakPersonaLayer)
    scene: SpeakSceneLayer = field(default_factory=SpeakSceneLayer)
    guidance: SpeakGuidanceLayer = field(default_factory=SpeakGuidanceLayer)
    user_text: str = ""
    wants_share: bool = False
    share_summary: str = ""
    reply_style: SpeakReplyStyle = field(default_factory=SpeakReplyStyle)
    notes: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def persona_dialogue(self) -> str:
        return self.persona.self_narrative

    @property
    def presence_static(self) -> str:
        return self.persona.state_portrait

    @property
    def dialogue_compressed(self) -> str:
        return self.persona.dialogue_compressed

    def build_system(self) -> str:
        from .prompt_stitch import assemble_turn_system

        return assemble_turn_system(self)

    def module_sections(self, *, system_assembled: str | None = None) -> list[tuple[str, str, str]]:
        from .trace import build_module_sections

        return build_module_sections(self, system_assembled=system_assembled)

    def summary_for_log(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "wants_share": self.wants_share,
            "share_summary": self.share_summary,
            "persona_self_narrative_chars": len(self.persona.self_narrative),
            "persona_stable_portrait_chars": len(self.persona.stable_portrait),
            "persona_state_portrait_chars": len(self.persona.state_portrait),
            "persona_dialogue_compressed_chars": len(self.persona.dialogue_compressed),
            "scene_world_chars": len(self.scene.world_scene),
            "guidance_context_distill_chars": len(self.guidance.context_distill),
            "guidance_working_memory_chars": len(self.guidance.working_memory),
            "system_chars": len(self.build_system()),
            "user_chars": len(self.user_text),
            "notes": list(self.notes),
        }
