from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LifeContextInput:
    """Life 层向 status 层传递的事实性上下文。

    设计原则
    --------
    只携带"发生了什么"，不携带任何情感解读或判断。
    情感诠释完全由 StatusSynthesizer 负责。

    字段
    ----
    date          : 对应的日期（ISO 格式，如 "2026-05-17"）
    event_lines   : 事实事件列表（每条为 LifeEvent.to_fact_line() 输出的单行文本）
                    使用文本而非对象，避免 life/status 两层之间产生类型强耦合
    story_phase   : 叙事阶段标签，描述当前所处的故事位置
                    这是叙事定位（如"初期建立"、"深入推进"），不是情感标签
    notable_flags : 特别标记（如"首次完成 milestone X"），供 synthesizer 着重关注
    """
    date: str = ""
    event_lines: list[str] = field(default_factory=list)
    story_phase: str = ""
    notable_flags: list[str] = field(default_factory=list)

    @classmethod
    def from_life_events(
        cls,
        events,
        date: str = "",
        story_phase: str = "",
    ) -> LifeContextInput:
        """从 LifeEvent 列表构建输入，负责调用 to_fact_line() 转换。

        events 类型为 list[LifeEvent]，用 Any 避免循环导入。
        """
        event_lines = [e.to_fact_line() for e in events]
        notable_flags = [
            e.to_fact_line()
            for e in events
            if getattr(e, "event_type", None) is not None
            and e.event_type.value == "milestone"
        ]
        return cls(
            date=date,
            event_lines=event_lines,
            story_phase=story_phase,
            notable_flags=notable_flags,
        )

    def is_empty(self) -> bool:
        return not self.event_lines and not self.story_phase and not self.notable_flags

    def render_for_prompt(self) -> str:
        """渲染为供 StatusSynthesizer 使用的事实摘要文本。"""
        parts: list[str] = []

        if self.date:
            parts.append(f"日期：{self.date}")

        if self.story_phase:
            parts.append(f"叙事阶段：{self.story_phase}")

        if self.event_lines:
            parts.append("近期事件（事实）：")
            parts.extend(f"  {line}" for line in self.event_lines)

        if self.notable_flags:
            parts.append("值得关注：")
            parts.extend(f"  * {flag}" for flag in self.notable_flags)

        return "\n".join(parts)
