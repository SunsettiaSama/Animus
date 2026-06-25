from __future__ import annotations

from dataclasses import dataclass, field

from .control import GuidanceTrigger


@dataclass
class SpeakGuidanceLayer:
    """引导层：对话引导叙述、社交弱主动、会话工作记忆；分享/记忆候选供规划器读取。"""

    control_arc: str = ""
    share_preview: str = ""
    recall_preview: str = ""
    interactor_portrait: str = ""
    social_blocks: list[str] = field(default_factory=list)
    context_distill: str = ""
    working_memory: str = ""

    @property
    def share(self) -> str:
        return self.share_preview

    @share.setter
    def share(self, value: str) -> None:
        self.share_preview = value

    def render_orchestrator_blocks(self) -> list[str]:
        """编排器动态块：引导 / 社交 / 记忆与分享候选预览，不含会话蒸馏与工作记忆。"""
        blocks: list[str] = []
        if self.control_arc.strip():
            blocks.append(self.control_arc.strip())
        if self.recall_preview.strip():
            blocks.append(self.recall_preview.strip())
        if self.share_preview.strip():
            blocks.append(self.share_preview.strip())
        for block in self.social_blocks:
            text = block.strip()
            if text:
                blocks.append(text)
        return blocks

    def render_blocks(self) -> list[str]:
        return self.render_orchestrator_blocks()
