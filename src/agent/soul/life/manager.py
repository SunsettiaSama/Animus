from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.status.life_bridge import LifeContextInput
from .factual.event import EventType, LifeEvent
from .factual.event_log import LifeEventLog
from .story.arc import StoryPhase
from .story.engine import StoryEngine
from .story.profile import LifeProfile, LifeProfileGenerator, LifeProfileStore
from .story.synthesis import DailySynthesizer, DailySynthesisResult

_NARRATIVE_SYSTEM = """\
你是一个AI助手，正在用第一人称记录自己刚刚完成的工作。
将以下任务清单转化为自然的叙事，30-80字，像日记一样。
不要列举，要叙述经历。"""


class LifeManager:
    """Life 子系统的统一协调器。

    两层职责
    --------
    factual（事实层）
        记录与用户的会话及各类事件，作为全系统的事实账本。
        可多可少，完全由实际发生的事驱动。
        核心：LifeEvent + LifeEventLog

    story（故事层）
        用小说式叙事引擎驱动 agent 的内心故事。
        主动规划叙事弧、章节与阶段，不被动等待事实触发。
        核心：StoryEngine + DailySynthesizer + LifeProfile

    对外接口
    --------
    factual 侧：
        record_session()  每次与用户的对话结束后调用
        record_event()    记录任意类型的事实事件

    story 侧：
        build_life_context()  构建供 status 层使用的 LifeContextInput
        run_daily_review()    日终回顾（事实整理 + 叙事阶段判断 + profile 刷新）
        advance_story()       手动推进叙事章节
    """

    def __init__(
        self,
        life_dir: str,
        llm: BaseLLM | None = None,
    ) -> None:
        self._life_dir = life_dir
        self._llm = llm

        # ── Factual 层 ────────────────────────────────────────────────────────
        self._event_log = LifeEventLog(life_dir)

        # ── Story 层 ──────────────────────────────────────────────────────────
        self._story = StoryEngine(life_dir, self._event_log)
        self._profile_store = LifeProfileStore(life_dir)
        self._profile: LifeProfile = LifeProfile()

        self._profile_generator: LifeProfileGenerator | None = (
            LifeProfileGenerator(llm) if llm is not None else None
        )
        self._synthesizer: DailySynthesizer | None = (
            DailySynthesizer(llm) if llm is not None else None
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def event_log(self) -> LifeEventLog:
        return self._event_log

    @property
    def story(self) -> StoryEngine:
        return self._story

    @property
    def profile(self) -> LifeProfile:
        return self._profile

    # ── Factual 层接口 ────────────────────────────────────────────────────────

    def record_session(
        self,
        description: str,
        source: str = "",
        duration_min: int = 0,
    ) -> LifeEvent:
        """记录一次与用户的对话会话（最常用的事实写入入口）。

        description 必须是事实陈述，例如：
          "完成了关于 soul 架构的5轮讨论，涉及 life/memory 分工"
        """
        return self.record_event(
            event_type=EventType.INTERACTION,
            description=description,
            source=source,
            duration_min=duration_min,
        )

    def record_event(
        self,
        event_type: EventType,
        description: str,
        source: str = "",
        duration_min: int = 0,
        **metadata,
    ) -> LifeEvent:
        """记录任意类型的事实事件，写入事实账本，通知故事引擎。"""
        event = LifeEvent.now(
            event_type=event_type,
            description=description,
            source=source,
            duration_min=duration_min,
            **metadata,
        )
        self._story.record_event_to_chapter(event)
        return event

    # ── Story 层接口 ──────────────────────────────────────────────────────────

    def build_life_context(self, days: int = 1) -> LifeContextInput:
        """构建供 status 层使用的 LifeContextInput。

        由故事引擎读取近期事实事件 + 当前叙事阶段组装。
        """
        date_str = datetime.now(timezone.utc).date().isoformat()
        return self._story.build_life_context(days=days, date_str=date_str)

    def advance_story(self, title: str, phase: StoryPhase) -> None:
        """手动推进叙事到新章节（由外部触发，如特殊里程碑事件）。"""
        self._story.advance_chapter(title=title, phase=phase)

    def load_profile(self) -> LifeProfile:
        stored = self._profile_store.load()
        if not stored.is_stale():
            self._profile = stored
        return self._profile

    def run_daily_review(
        self,
        static_profile: PersonaProfile,
        today_medium_term: str = "",
        today_scheduler_tasks: str = "",
        scheduler_engine=None,
    ) -> tuple[DailySynthesisResult, LifeContextInput] | None:
        """日终回顾：事实整理 + 叙事阶段判断 + profile 刷新。

        Returns
        -------
        (result, life_ctx)
            result   : 包含 scheduler_actions / thought_records / virtual_content
            life_ctx : 供 persona_manager 推送给 status 层的事实上下文
        None 表示 LLM 不可用，跳过。
        """
        if self._synthesizer is None:
            return None

        detected_phase = self._story.auto_detect_phase(recent_days=7)
        if detected_phase != self._story.current_phase:
            self._story.advance_chapter(
                title=f"进入{detected_phase.value}阶段",
                phase=detected_phase,
            )

        result, life_ctx = self._synthesizer.run(
            static_profile=static_profile,
            today_medium_term=today_medium_term,
            today_scheduler_tasks=today_scheduler_tasks,
            event_log=self._event_log,
            story_phase=self._story.current_phase.value,
        )

        if scheduler_engine is not None and result.scheduler_actions:
            self._schedule_actions(result.scheduler_actions, scheduler_engine)

        if self._profile_generator is not None:
            new_profile = self._profile_generator.generate(
                static_profile=static_profile,
                event_log=self._event_log,
                medium_term_distillate=today_medium_term,
            )
            self._profile = new_profile
            self._profile_store.save(new_profile)

        return result, life_ctx

    def _schedule_actions(self, actions: list[dict], engine) -> None:
        for action in actions:
            name = action.get("name", "").strip()
            instruction = action.get("instruction", "").strip()
            if not name or not instruction:
                continue
            trigger_type = action.get("trigger_type", "once")
            delivery = action.get("delivery", "push")
            at_str = action.get("at", "")

            existing = [
                t for t in engine.list_timeline()
                if t.name == name and t.status.value in ("pending", "running")
            ]
            if existing:
                continue

            if trigger_type == "once" and at_str:
                dt = datetime.fromisoformat(at_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                engine.schedule_once(name, instruction, dt, profile="full", delivery=delivery)
            elif trigger_type == "cron":
                cron_expr = action.get("cron_expr", "")
                if cron_expr:
                    engine.schedule_cron(name, instruction, cron_expr, profile="full", delivery=delivery)
