"""infra.agent 端口：仅 ActionRunner。LLM 直接用 infra.llm.BaseLLM。"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ActionRunner(Protocol):
    """执行一组 action call；工具失败写成 observation 字符串，不 raise。"""

    def run(self, calls: list[dict]) -> list[dict]:
        """
        Parameters
        ----------
        calls:
            [{"action": str, "args": dict}, ...]

        Returns
        -------
        list[{"tool": str, "observation": str}]
        """
        ...
