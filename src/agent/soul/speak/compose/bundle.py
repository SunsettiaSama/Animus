from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .injected import SpeakInjectedContext
from .reply_style import SpeakReplyStyle
from .system import SpeakSystemPrompt, SpeakTurnMode

__all__ = ["SpeakPromptBundle", "SpeakTurnMode"]


@dataclass
class SpeakPromptBundle:
    """Speak 一轮 prompt：外部注入 + 系统提示词，向上层传递。"""

    session_id: str
    mode: SpeakTurnMode = "inbound"
    injected: SpeakInjectedContext = field(default_factory=SpeakInjectedContext)
    system: SpeakSystemPrompt = field(default_factory=SpeakSystemPrompt)
    wants_share: bool = False
    share_summary: str = ""
    reply_style: SpeakReplyStyle = field(default_factory=SpeakReplyStyle)
    notes: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    social_blocks: list[str] = field(default_factory=list)

    @property
    def persona_traits(self) -> str:
        return self.injected.persona.traits

    @property
    def self_concept(self) -> str:
        return self.injected.persona.self_concept

    @property
    def presence_static(self) -> str:
        return self.injected.status.presence

    @property
    def dialogue_compressed(self) -> str:
        return self.injected.status.dialogue_compressed

    @property
    def user_text(self) -> str:
        return self.injected.user_text

    def build_system(self) -> str:
        parts: list[str] = []
        role = self.system.role.strip()
        if role:
            parts.append(role)
        for block in self.injected.render_system_blocks():
            parts.append(block)
        for block in self.social_blocks:
            text = block.strip()
            if text:
                parts.append(text)
        share = self.system.share.strip()
        if share:
            parts.append(share)
        output_format = self.system.output_format.strip()
        if output_format:
            parts.append(output_format)
        return "\n\n".join(parts)

    def module_sections(self, *, system_assembled: str | None = None) -> list[tuple[str, str, str]]:
        from .trace_modules import build_module_sections

        return build_module_sections(self, system_assembled=system_assembled)

    def summary_for_log(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "wants_share": self.wants_share,
            "share_summary": self.share_summary,
            "persona_traits_chars": len(self.persona_traits),
            "self_concept_chars": len(self.self_concept),
            "status_presence_chars": len(self.injected.status.presence),
            "status_dialogue_compressed_chars": len(self.dialogue_compressed),
            "system_chars": len(self.build_system()),
            "user_chars": len(self.user_text),
            "notes": list(self.notes),
        }
