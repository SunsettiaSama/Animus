from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WakeResult:
    """起床自叙结果。"""

    session_id: str
    applied: bool
    source: str = "llm"
    narratives: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class SleepResult:
    """休眠清理结果。"""

    session_id: str
    applied: bool
    reason: str = ""
