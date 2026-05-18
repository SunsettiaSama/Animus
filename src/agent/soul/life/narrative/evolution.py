from __future__ import annotations

import logging

from agent.soul.persona.status.life_bridge import LifeContextInput

from .arc import Chapter, StoryArc, StoryArcStore, StoryPhase
from .event import NarrativeEvent, NarrativeEventKind
from .event_log import NarrativeEventLog

logger = logging.getLogger(__name__)

_MILESTONE_PHASE_MAP: dict[str, StoryPhase] = {
    "首次": StoryPhase.ESTABLISHING,
    "突破": StoryPhase.TRANSFORMING,
    "转折": StoryPhase.TRANSFORMING,
    "回顾": StoryPhase.REFLECTING,
    "总结": StoryPhase.REFLECTING,
}


def narrative_timeline_entries(events: list[NarrativeEvent]) -> list[tuple[str, str]]:
    return [(e.ts, e.to_fact_line()) for e in events]


def merge_timeline_pairs(
    ledger_entries: list[tuple[str, str]],
    narrative_entries: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    pairs = list(ledger_entries) + list(narrative_entries)
    pairs.sort(key=lambda x: x[0])
    return pairs


def merged_fact_lines_chronologically(
    ledger_entries: list[tuple[str, str]],
    narrative_entries: list[tuple[str, str]],
) -> list[str]:
    return [line for _, line in merge_timeline_pairs(ledger_entries, narrative_entries)]


def infer_story_phase(
    arc: StoryArc,
    *,
    dialogue_count: int,
    narrative_log: NarrativeEventLog,
    recent_days: int = 7,
) -> StoryPhase:
    milestones = [
        e
        for e in narrative_log.recent(days=recent_days)
        if e.kind == NarrativeEventKind.MILESTONE
    ]

    for m in milestones:
        for kw, phase in _MILESTONE_PHASE_MAP.items():
            if kw in m.description:
                return phase

    current = arc.current_phase
    if dialogue_count >= 30 and current == StoryPhase.ESTABLISHING:
        return StoryPhase.DEVELOPING
    if dialogue_count >= 80 and current == StoryPhase.DEVELOPING:
        return StoryPhase.MATURING
    return current


def format_timeline_digest_for_profile(
    ledger_entries: list[tuple[str, str]],
    narrative_events: list[NarrativeEvent],
    *,
    tail: int = 20,
) -> str:
    pairs = merge_timeline_pairs(ledger_entries, narrative_timeline_entries(narrative_events))
    rows = [f"[{ts[:10]}] {line}" for ts, line in pairs[-tail:]]
    return "\n".join(rows)


class NarrativeArcEvolver:
    """叙事弧演化：里程碑挂钩、阶段推断、合并时间线构造 LifeContextInput。

    调用时机由 heartbeat 等上层约定（如日更）；本类只实现叙事侧演化规则。
    """

    def __init__(self, life_dir: str, narrative_log: NarrativeEventLog) -> None:
        self._arc_store = StoryArcStore(life_dir)
        self._arc: StoryArc = self._arc_store.load()
        self._narrative_log = narrative_log

    @property
    def arc(self) -> StoryArc:
        return self._arc

    @property
    def current_phase(self) -> StoryPhase:
        return self._arc.current_phase

    @property
    def current_chapter(self) -> Chapter | None:
        return self._arc.current_chapter

    def advance_chapter(self, title: str, phase: StoryPhase) -> Chapter:
        chapter = self._arc.open_chapter(title=title, phase=phase)
        self._arc_store.save(self._arc)
        logger.info("[Narrative] 新章节开启：%s (%s)", title, phase.value)
        return chapter

    def mark_key_event(self, event_id: str) -> None:
        self._arc.add_key_event(event_id)
        self._arc_store.save(self._arc)

    def after_narrative_recorded(self, event: NarrativeEvent) -> None:
        if event.kind == NarrativeEventKind.MILESTONE:
            self.mark_key_event(event.id)

    def detect_phase(self, dialogue_count: int, recent_days: int = 7) -> StoryPhase:
        return infer_story_phase(
            self._arc,
            dialogue_count=dialogue_count,
            narrative_log=self._narrative_log,
            recent_days=recent_days,
        )

    def build_life_context(
        self,
        ledger_entries: list[tuple[str, str]],
        *,
        days: int = 1,
        date_str: str = "",
    ) -> LifeContextInput:
        from datetime import datetime, timezone

        if not date_str:
            date_str = datetime.now(timezone.utc).date().isoformat()

        ne = self._narrative_log.recent(days=days)
        nar_pairs = narrative_timeline_entries(ne)
        event_lines = merged_fact_lines_chronologically(ledger_entries, nar_pairs)

        milestone_lines = [
            e.to_fact_line()
            for e in ne
            if e.kind == NarrativeEventKind.MILESTONE
        ]

        ctx = LifeContextInput(
            date=date_str,
            event_lines=event_lines,
            story_phase=self._arc.current_phase.value,
            notable_flags=list(milestone_lines),
        )

        ch = self._arc.current_chapter
        if ch and ch.title:
            ctx.notable_flags.insert(0, f"[当前章节] {ch.title}")

        return ctx
