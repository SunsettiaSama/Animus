from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NarrativeBrief:
    """向故事观引擎发起的叙事请求。"""

    hint: str
    profile_narrative: str = ""
    memory_lines: list[str] = field(default_factory=list)
    dice_tendency: str = ""
    query: str = ""


@dataclass(frozen=True)
class StoryBeat:
    """一段符合故事观的叙事产出。"""

    text: str
    emotion_label: str = ""
    emotion_intensity: float = 0.45
    chapter_hint: str = ""
