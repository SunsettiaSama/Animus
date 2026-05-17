from __future__ import annotations

import logging

from agent.soul.persona.status.life_bridge import LifeContextInput
from ..factual.event import EventType, LifeEvent
from ..factual.event_log import LifeEventLog
from .arc import Chapter, StoryArc, StoryArcStore, StoryPhase

logger = logging.getLogger(__name__)

_MILESTONE_PHASE_MAP: dict[str, StoryPhase] = {
    "首次": StoryPhase.ESTABLISHING,
    "突破": StoryPhase.TRANSFORMING,
    "转折": StoryPhase.TRANSFORMING,
    "回顾": StoryPhase.REFLECTING,
    "总结": StoryPhase.REFLECTING,
}


class StoryEngine:
    """故事引擎——规划和追踪 agent 的人生叙事，为 status 层提供叙事定位。

    职责
    ----
    - 管理叙事弧（StoryArc）：章节开启、关闭、阶段推进
    - 读取事实账本（LifeEventLog），识别重要事件并关联到当前章节
    - 构建 LifeContextInput，向 status 层传递"现在处于故事哪里"

    不做情感判断——情感诠释交由 StatusSynthesizer 完成。
    """

    def __init__(self, life_dir: str, event_log: LifeEventLog) -> None:
        self._arc_store = StoryArcStore(life_dir)
        self._arc: StoryArc = self._arc_store.load()
        self._event_log = event_log

    @property
    def arc(self) -> StoryArc:
        return self._arc

    @property
    def current_phase(self) -> StoryPhase:
        return self._arc.current_phase

    @property
    def current_chapter(self) -> Chapter | None:
        return self._arc.current_chapter

    # ── 章节管理 ──────────────────────────────────────────────────────────────

    def advance_chapter(self, title: str, phase: StoryPhase) -> Chapter:
        """手动推进到新章节（由 DailySynthesizer 或外部触发）。"""
        chapter = self._arc.open_chapter(title=title, phase=phase)
        self._arc_store.save(self._arc)
        logger.info("[Story] 新章节开启：%s (%s)", title, phase.value)
        return chapter

    def mark_key_event(self, event_id: str) -> None:
        """将某个 LifeEvent 标记为当前章节的关键事件。"""
        self._arc.add_key_event(event_id)
        self._arc_store.save(self._arc)

    def auto_detect_phase(self, recent_days: int = 7) -> StoryPhase:
        """根据近期事件自动推断叙事阶段（启发式，不调用 LLM）。

        规则
        ----
        - 有 milestone 事件 → 优先检查描述关键词判断是否需要推进
        - 近期 interaction 数量决定阶段深度（粗粒度参考）
        """
        events = self._event_log.recent(days=recent_days)
        milestones = [e for e in events if e.event_type == EventType.MILESTONE]

        for m in milestones:
            for kw, phase in _MILESTONE_PHASE_MAP.items():
                if kw in m.description:
                    return phase

        interactions = [e for e in events if e.event_type == EventType.INTERACTION]
        count = len(interactions)
        current = self._arc.current_phase
        if count >= 30 and current == StoryPhase.ESTABLISHING:
            return StoryPhase.DEVELOPING
        if count >= 80 and current == StoryPhase.DEVELOPING:
            return StoryPhase.MATURING
        return current

    # ── 向 status 层构建上下文 ─────────────────────────────────────────────────

    def build_life_context(self, days: int = 1, date_str: str = "") -> LifeContextInput:
        """读取近期事实事件 + 当前叙事阶段，构建 LifeContextInput。

        这是 story engine → status 层的标准接口。
        """
        from datetime import datetime, timedelta, timezone
        if not date_str:
            date_str = datetime.now(timezone.utc).date().isoformat()

        events = self._event_log.recent(days=days)
        phase = self._arc.current_phase.value

        ctx = LifeContextInput.from_life_events(
            events=events,
            date=date_str,
            story_phase=phase,
        )

        ch = self._arc.current_chapter
        if ch and ch.title:
            ctx.notable_flags.insert(0, f"[当前章节] {ch.title}")

        return ctx

    def record_event_to_chapter(self, event: LifeEvent) -> None:
        """将 LifeEvent 写入事实账本，并在必要时关联到当前章节。"""
        self._event_log.append(event)
        if event.event_type == EventType.MILESTONE:
            self.mark_key_event(event.id)
