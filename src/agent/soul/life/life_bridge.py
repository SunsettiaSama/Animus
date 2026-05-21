from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LifeContextInput:
    """Life 层向外传递的事实性上下文（供下游按需消费）。

    只携带「发生了什么」，不携带情感解读。
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
        event_lines = [e.to_fact_line() for e in events]
        notable_flags = []
        for e in events:
            kind = getattr(e, "kind", None)
            val = getattr(kind, "value", kind)
            if val == "milestone":
                notable_flags.append(e.to_fact_line())
        return cls(
            date=date,
            event_lines=event_lines,
            story_phase=story_phase,
            notable_flags=notable_flags,
        )

    def is_empty(self) -> bool:
        return not self.event_lines and not self.story_phase and not self.notable_flags

    def render_for_prompt(self) -> str:
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
