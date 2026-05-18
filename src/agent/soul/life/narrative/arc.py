from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class StoryPhase(str, Enum):
    """叙事阶段——描述 agent 当前所处的故事位置，供 status 层进行情感诠释。

    这是叙事定位标签，不是情感判断。
    """
    ESTABLISHING  = "初期建立"   # 建立关系，摸索边界，形成初步互动模式
    DEVELOPING    = "深入推进"   # 深化互动，发展稳定模式，积累共同经验
    MATURING      = "成熟稳定"   # 节奏成形，形成习惯，关系趋于稳定
    TRANSFORMING  = "转折变化"   # 重大事件或关系变化，节奏被打破
    REFLECTING    = "回顾沉淀"   # 回望过去，整合经验，准备进入新阶段


@dataclass
class Chapter:
    """故事中的一个章节——记录一段完整的叙事弧。

    字段
    ----
    id              : 唯一标识
    title           : 章节标题（叙事性描述，如"与用户建立初步信任的阶段"）
    phase           : 该章节对应的叙事阶段
    started_at      : 章节开始时间（ISO UTC）
    ended_at        : 章节结束时间（空表示进行中）
    key_event_ids   : 该章节中具有代表性的叙事事件 id（如 NarrativeEvent.id）
    summary         : 该章节的叙事摘要（由 NarrativeArcEvolver / LLM 生成）
    """
    id:             str
    title:          str
    phase:          StoryPhase
    started_at:     str
    ended_at:       str = ""
    key_event_ids:  list[str] = field(default_factory=list)
    summary:        str = ""

    @staticmethod
    def new(title: str, phase: StoryPhase) -> Chapter:
        return Chapter(
            id=str(uuid.uuid4()),
            title=title,
            phase=phase,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    def is_active(self) -> bool:
        return not self.ended_at

    def close(self, summary: str = "") -> None:
        self.ended_at = datetime.now(timezone.utc).isoformat()
        if summary:
            self.summary = summary

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "phase": self.phase.value,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "key_event_ids": self.key_event_ids,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Chapter:
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            title=d.get("title", ""),
            phase=StoryPhase(d.get("phase", StoryPhase.ESTABLISHING.value)),
            started_at=d.get("started_at", ""),
            ended_at=d.get("ended_at", ""),
            key_event_ids=d.get("key_event_ids", []),
            summary=d.get("summary", ""),
        )


_ARC_FILENAME = "story_arc.json"


@dataclass
class StoryArc:
    """agent 的人生叙事弧——所有章节的集合，追踪当前叙事位置。"""
    chapters: list[Chapter] = field(default_factory=list)

    @property
    def current_chapter(self) -> Chapter | None:
        for ch in reversed(self.chapters):
            if ch.is_active():
                return ch
        return None

    @property
    def current_phase(self) -> StoryPhase:
        ch = self.current_chapter
        return ch.phase if ch is not None else StoryPhase.ESTABLISHING

    def open_chapter(self, title: str, phase: StoryPhase) -> Chapter:
        active = self.current_chapter
        if active is not None:
            active.close()
        chapter = Chapter.new(title=title, phase=phase)
        self.chapters.append(chapter)
        return chapter

    def add_key_event(self, event_id: str) -> None:
        ch = self.current_chapter
        if ch is not None and event_id not in ch.key_event_ids:
            ch.key_event_ids.append(event_id)

    def to_dict(self) -> dict:
        return {"chapters": [c.to_dict() for c in self.chapters]}

    @classmethod
    def from_dict(cls, d: dict) -> StoryArc:
        return cls(chapters=[Chapter.from_dict(c) for c in d.get("chapters", [])])


class StoryArcStore:
    def __init__(self, life_dir: str) -> None:
        self._path = Path(life_dir) / _ARC_FILENAME

    def load(self) -> StoryArc:
        if not self._path.exists():
            arc = StoryArc()
            arc.open_chapter("初次相遇", StoryPhase.ESTABLISHING)
            return arc
        with open(self._path, encoding="utf-8") as f:
            return StoryArc.from_dict(json.load(f))

    def save(self, arc: StoryArc) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(arc.to_dict(), f, ensure_ascii=False, indent=2)
