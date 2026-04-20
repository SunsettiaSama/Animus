from __future__ import annotations

from typing import Literal

from react.action.base import BaseAction


class BaseSkill(BaseAction):
    """
    技能基类。

    技能是比单个工具更高层的能力单元，可以：
    - simple   : 单步执行（与 BaseAction 等价，但携带版本/类型元信息）
    - chain    : 串行组合多个工具/技能
    - parallel : 并行执行多个子任务后汇总

    所有技能对 Agent 来说与普通工具无异（同样通过 execute() 调用），
    区别仅在于内部实现的复杂程度。
    """

    skill_type: Literal["simple", "chain", "parallel"] = "simple"
    version: str = "1.0.0"

    def execute(self, **kwargs) -> str:
        raise NotImplementedError
