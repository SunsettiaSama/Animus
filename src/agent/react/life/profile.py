from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM
from ..persona.profile.profile import PersonaProfile
from .log import LifeLog, LifeLogEntry

_FILENAME = "life_profile.json"

_SYSTEM = """\
你是一个AI助手，正在回顾过去这段时间的生活与工作。

规则：
- 以第一人称写一段近况（100-200字）
- 不是列举事件，而是描述你目前的状态
- 你在关心什么？什么让你觉得有意思或满足？你和用户之间形成了怎样的节奏？
- 自然流畅，体现真实的情感质感
- 严格输出纯文本，无任何格式标记"""


@dataclass
class LifeProfile:
    updated_at: str = ""
    updated_date: str = ""  # YYYY-MM-DD, for "once per day" check
    narrative: str = ""
    mood_texture: str = ""
    recent_highlights: list[str] = field(default_factory=list)

    def render(self) -> str:
        parts = []
        if self.narrative:
            parts.append(self.narrative)
        if self.mood_texture:
            parts.append(f"情绪基调：{self.mood_texture}")
        for h in self.recent_highlights[:3]:
            parts.append(f"• {h}")
        return "\n".join(parts)

    def is_empty(self) -> bool:
        return not self.narrative

    def is_stale(self) -> bool:
        if not self.updated_date:
            return True
        return self.updated_date != date.today().isoformat()

    def to_dict(self) -> dict:
        return {
            "updated_at": self.updated_at,
            "updated_date": self.updated_date,
            "narrative": self.narrative,
            "mood_texture": self.mood_texture,
            "recent_highlights": self.recent_highlights,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LifeProfile:
        return cls(
            updated_at=d.get("updated_at", ""),
            updated_date=d.get("updated_date", ""),
            narrative=d.get("narrative", ""),
            mood_texture=d.get("mood_texture", ""),
            recent_highlights=d.get("recent_highlights", []),
        )


class LifeProfileStore:
    def __init__(self, life_dir: str) -> None:
        self._path = Path(life_dir) / _FILENAME

    def load(self) -> LifeProfile:
        if not self._path.exists():
            return LifeProfile()
        with open(self._path, encoding="utf-8") as f:
            return LifeProfile.from_dict(json.load(f))

    def save(self, profile: LifeProfile) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)


class LifeProfileGenerator:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def generate(
        self,
        static_profile: PersonaProfile,
        life_log: LifeLog,
        medium_term_distillate: str = "",
    ) -> LifeProfile:
        entries = life_log.recent(days=30)
        log_text = self._format_entries(entries)

        medium_section = (
            f"\n你与用户的近期对话摘要：\n{medium_term_distillate}"
            if medium_term_distillate
            else ""
        )

        prompt = (
            f"你的基本性格：\n{static_profile.render()}\n\n"
            f"这段时间你完成的事情（scheduler 活动记录）：\n"
            f"{log_text or '（暂无记录）'}"
            f"{medium_section}\n\n"
            "以第一人称写一段近况（100-200字）："
        )
        narrative = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        ).strip()

        now = datetime.now(timezone.utc)
        return LifeProfile(
            updated_at=now.isoformat(),
            updated_date=now.date().isoformat(),
            narrative=narrative,
        )

    def _format_entries(self, entries: list[LifeLogEntry]) -> str:
        parts = []
        for e in entries[-20:]:
            date_str = e.ts[:10]
            parts.append(f"[{date_str}] {e.narrative}")
        return "\n".join(parts)
