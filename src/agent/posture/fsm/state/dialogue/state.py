from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DialogueStance:
    """当前对话结构状态 — posture 仅持有线路与主动意图关联。"""

    line_open: bool = False
    proactive_intent_id: str = ""

    def copy(self) -> DialogueStance:
        return DialogueStance(
            line_open=self.line_open,
            proactive_intent_id=self.proactive_intent_id,
        )

    def reset(self) -> None:
        self.line_open = False
        self.proactive_intent_id = ""
