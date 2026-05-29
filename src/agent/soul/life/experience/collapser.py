from __future__ import annotations

from typing import Protocol

from .unit import ExperienceUnit


class ExperienceCollapser(Protocol):
    """多路体验交会时的重新表述协议。

    当 ``{user, narrative, surprise}`` 中的两路或三路体验在时间窗口内相遇，
    ``ExperienceOrchestrator`` 调用 ``collapse()``，由 API（通常是 LLM）
    将所有参与单元重新表述为一段新叙事，描述"这些事交会在一起时实际发生了什么"。

    参数
    ----
    ``units`` — 参与交会的体验单元列表（2 或 3 个，来源各不相同）：
      - ``source="user"``      — 用户说了什么
      - ``source="narrative"`` — 地标叙事意图
      - ``source="surprise"``  — 意外事件

    注意
    ----
    新 collision unit 的情感字段继承参与单元中 salience 最高者；
    是否写入记忆图由 ``ExperienceUnit.should_promote_to_memory()``（自叙正则）决定。
    """

    def collapse(self, units: list[ExperienceUnit]) -> str:
        """返回重新表述后的交会叙事文本。"""
        ...


class NullCollapser:
    """占位实现——无 LLM 时，将各路体验核心内容拼接。"""

    def collapse(self, units: list[ExperienceUnit]) -> str:
        parts: list[str] = []
        for u in units:
            text = (u.situation.perception or u.situation.narration or u.action.content)[:50]
            parts.append(f"（{u.source}）{text}")
        return " × ".join(parts)
