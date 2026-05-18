from __future__ import annotations

from typing import Protocol

from .unit import ExperienceUnit


class ExperienceCollapser(Protocol):
    """用户体验与叙事体验交会时的重新表述协议。

    当 ``source="user"`` 的体验与 ``source="narrative"`` 的体验在时间上
    相距不足指定窗口（默认 30 分钟），说明现实发生的对话与 Agent 自行安排
    的内在叙事在同一时刻相遇了。

    此时调用 ``collapse()``，由 API（通常是 LLM）将两者重新表述为一段
    新的叙事文本，描述"这两件事交会在一起时，实际发生了什么"。

    注意
    ----
    - 新 unit 的情感字段（``ExperienceFeeling``）从零开始，不继承原始两个 unit
      的任何情感倾向，由叙事文本本身携带情绪信息
    - 原始两个 unit 标记为已折叠（orchestrator 内维护），不再重复处理
    """

    def collapse(
        self,
        user_unit: ExperienceUnit,
        narrative_unit: ExperienceUnit,
    ) -> str:
        """返回重新表述后的交会叙事文本。"""
        ...


class NullCollapser:
    """占位实现——无 LLM 时的降级，将两个体验的核心内容拼接。"""

    def collapse(
        self,
        user_unit: ExperienceUnit,
        narrative_unit: ExperienceUnit,
    ) -> str:
        u = (user_unit.situation.perception or user_unit.action.content)[:60]
        n = (narrative_unit.situation.narration or narrative_unit.action.content)[:60]
        return f"（用户）{u} × （叙事）{n}"
