from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TuringVerdictKind(str, Enum):
    agent = "AGENT"
    not_agent = "NOT_AGENT"
    unknown = "UNKNOWN"


@dataclass(frozen=True)
class TuringTurn:
    user: str
    agent: str
    thought: str = ""
    actions: tuple[str, ...] = ()
    session_state: str = ""
    raw: str = ""


@dataclass
class TuringTranscript:
    """供外部裁决器阅读的 Soul 对话样本。"""

    session_id: str
    persona_name: str = ""
    turns: list[TuringTurn] = field(default_factory=list)
    presence_digest: str = ""
    control_group: bool = False

    def render_for_judge(self) -> str:
        header = "【对照组：模板客服】" if self.control_group else "【受测主体：Soul Speak】"
        lines = [
            header,
            f"session_id: {self.session_id}",
        ]
        if self.persona_name:
            lines.append(f"persona: {self.persona_name}")
        if self.presence_digest:
            lines.append(f"presence: {self.presence_digest}")
        lines.append("")
        for idx, turn in enumerate(self.turns, start=1):
            lines.append(f"--- turn {idx} ---")
            lines.append(f"user: {turn.user}")
            if turn.thought:
                lines.append(f"think: {turn.thought}")
            for action in turn.actions:
                lines.append(f"action: {action}")
            lines.append(f"speak: {turn.agent}")
            if turn.session_state:
                lines.append(f"state: {turn.session_state}")
            if turn.raw and turn.raw != turn.agent:
                lines.append(f"raw: {turn.raw[:800]}")
            lines.append("")
        return "\n".join(lines).strip()


@dataclass(frozen=True)
class TuringVerdict:
    kind: TuringVerdictKind
    reason: str = ""
    layer: str = "external"

    @property
    def is_agent(self) -> bool:
        return self.kind == TuringVerdictKind.agent
