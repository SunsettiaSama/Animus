from __future__ import annotations

from dataclasses import dataclass

from infra.agent.unit import Unit


@dataclass
class CharacterContextUnit(Unit):
    """角色当前帧上下文卡片（对话/调度材料摘要）。"""

    title: str = ""
    body: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "character_context"
        if not self.source:
            self.source = "character"

    def render(self) -> str:
        title = self.title.strip() or "上下文"
        body = self.body.strip()
        if not body:
            return ""
        return f"[角色卡片·{title}]\n{body}"


@dataclass
class CharacterHelpObservationUnit(Unit):
    """io→worker 回传；不对角色暴露工具细节。"""

    observation: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            self.kind = "character_help_obs"
        if not self.source:
            self.source = "character.io"

    def render(self) -> str:
        text = self.observation.strip()
        return f"[后台回传]\n{text}" if text else ""
