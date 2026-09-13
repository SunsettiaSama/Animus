from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.soul.speak.session.queue import UserInputItem


@dataclass
class DirectPipelineRunner:
    """direct 旁路管线：帧内零前置 LLM 调用，用户直达角色。

    - 不启动导演席位线程；
    - 不经热路径预决策（沉默权由角色在生成中自行行使）；
    - 投递用静态节奏模板；注意力债与去重在生成后重试层兜底。
    """

    run_direct_turn: Callable[[UserInputItem], Any]

    def run(self, item: UserInputItem):
        result = self.run_direct_turn(item)
        result.meta["pipeline"] = "direct"
        if "direct_pipeline" not in result.notes:
            result.notes.append("direct_pipeline")
        return result
