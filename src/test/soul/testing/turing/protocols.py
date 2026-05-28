from __future__ import annotations

from typing import Protocol


class ExternalAgentJudgeHandler(Protocol):
    """伪图灵测试：外部 agent 裁决受测主体是否呈现为 agent。"""

    def complete(self, system: str, user: str) -> str: ...
