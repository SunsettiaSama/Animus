from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DialogueBlock:
    """一轮用户-agent 对话块（非 agent 自驱块）。"""

    user_text: str
    agent_text: str
    perception: str = ""
    narration: str = ""
    prior_thought: str = ""


def is_user_agent_dialogue(block: DialogueBlock) -> bool:
    """仅统计用户参与的交互块；排除 agent 自驱（无用户话语）。"""
    return bool(block.user_text.strip())


@dataclass
class DialogueSessionTracker:
    block_count: int = 0
    blocks: list[DialogueBlock] = field(default_factory=list)

    def record(self, block: DialogueBlock) -> int:
        self.block_count += 1
        self.blocks.append(block)
        return self.block_count
