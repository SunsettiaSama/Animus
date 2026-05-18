from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from infra.llm import BaseLLM
from agent.soul.heartbeat.bridge import MemoryHeartbeatResult
from agent.soul.persona.profile.profile import PersonaProfile
from agent.soul.persona.status.life_bridge import LifeContextInput

from .ledger import (
    LedgerEvent,
    LedgerEventKind,
    LedgerEventLog,
    append_scheduler_digest,
    count_dialogue_recent,
    timeline_entries_recent,
)
from .narrative import (
    DailySynthesizer,
    DailySynthesisResult,
    LifeProfile,
    LifeProfileGenerator,
    LifeProfileStore,
    NarrativeArcEvolver,
    NarrativeEvent,
    NarrativeEventKind,
    NarrativeEventLog,
    StoryPhase,
    format_timeline_digest_for_profile,
)
from .experience import ExperienceBuilder, ExperienceLog
from .experience.unit import ExperienceActionKind
from .orchestrator import ExperienceOrchestrator, MemoryIngestPort
from .chronicle import ChronicleStore
from .journal import JournalStore, LifeJournal
from .service import LifeService

if TYPE_CHECKING:
    pass


class LifeManager:
    """Life 模块统一入口。

    职责
    ----
    - 维护旧有 ledger / narrative 路径（向后兼容 heartbeat / tao.py）
    - 构建并持有新架构的完整服务栈：
      ExperienceLog → ExperienceOrchestrator → ExperienceBuilder → LifeService
      ChronicleStore（客观事实）+ LifeJournal（手账）
    - 将每次用户回合和心跳体验下发至 LifeService 异步处理
    """

    def __init__(
        self,
        life_dir: str,
        llm: BaseLLM | None = None,
        memory_port: MemoryIngestPort | None = None,
    ) -> None:
        self._llm = llm
        self._life_dir = life_dir

        # ── 旧有路径（narrative / ledger）────────────────────────────────────
        self._ledger_log = LedgerEventLog(life_dir)
        self._narrative_log = NarrativeEventLog(life_dir)
        self._narrative_evolver = NarrativeArcEvolver(life_dir, self._narrative_log)
        self._profile_store = LifeProfileStore(life_dir)
        self._profile: LifeProfile = LifeProfile()
        self._profile_generator: LifeProfileGenerator | None = (
            LifeProfileGenerator(llm) if llm is not None else None
        )
        self._synthesizer: DailySynthesizer | None = (
            DailySynthesizer(llm) if llm is not None else None
        )

        # ── 新架构服务栈 ──────────────────────────────────────────────────────
        self._exp_log = ExperienceLog(life_dir)
        self._orchestrator = ExperienceOrchestrator(
            log=self._exp_log,
            memory_port=memory_port,
        )
        self._chronicle_store = ChronicleStore(life_dir)
        self._journal_store = JournalStore(life_dir)
        self._journal: LifeJournal = self._journal_store.load()
        self._builder = ExperienceBuilder(
            orchestrator=self._orchestrator,
            chronicle_store=self._chronicle_store,
        )
        self._life_service = LifeService(
            builder=self._builder,
            journal=self._journal,
            journal_store=self._journal_store,
        )
        self._life_service.start()

        self._turn_index: int = 0

    # ── 新架构属性 ────────────────────────────────────────────────────────────

    @property
    def life_service(self) -> LifeService:
        return self._life_service

    @property
    def journal(self) -> LifeJournal:
        return self._journal

    def save_journal(self) -> None:
        """将当前手账状态持久化（Agent 更新议程后调用）。"""
        self._journal_store.save(self._journal)

    def add_landmark(
        self,
        intention: str,
        scheduled_at: str,
        context: str = "",
    ) -> bool:
        """向手账追加一个地标并持久化，今日已达上限时返回 False。"""
        lm = self._journal.add_landmark(intention, scheduled_at, context)
        if lm is None:
            return False
        self._journal_store.save(self._journal)
        return True

    def set_landmark_filler(self, filler) -> None:
        """注入地标填充器实现（LLM 就绪后调用）。"""
        self._life_service.set_filler(filler)

    def set_collapser(self, collapser) -> None:
        """注入交会折叠器实现（LLM 就绪后调用）。"""
        self._orchestrator.set_collapser(collapser)

    def set_memory_port(self, memory_port: MemoryIngestPort) -> None:
        """启动后注入记忆层接口（tao.py 在 MemoryService 就绪后调用）。"""
        self._orchestrator._memory_port = memory_port

    def stop(self) -> None:
        """优雅关闭后台线程服务。"""
        self._life_service.stop()

    # ── 旧有路径属性 ──────────────────────────────────────────────────────────

    @property
    def ledger_log(self) -> LedgerEventLog:
        return self._ledger_log

    @property
    def narrative_log(self) -> NarrativeEventLog:
        return self._narrative_log

    @property
    def narrative_evolver(self) -> NarrativeArcEvolver:
        return self._narrative_evolver

    @property
    def profile(self) -> LifeProfile:
        return self._profile

    def record_session(
        self,
        description: str,
        source: str = "",
        duration_min: int = 0,
        **metadata,
    ) -> LedgerEvent:
        ev = LedgerEvent.now(
            LedgerEventKind.TAO_DIALOGUE,
            description,
            source=source,
            duration_min=duration_min,
            **metadata,
        )
        self._ledger_log.append(ev)
        return ev

    def record_story_beat(
        self,
        description: str,
        source: str = "story_engine",
        duration_min: int = 0,
        **metadata,
    ) -> NarrativeEvent:
        ev = NarrativeEvent.now(
            NarrativeEventKind.STORY_BEAT,
            description,
            source=source,
            duration_min=duration_min,
            **metadata,
        )
        self._narrative_log.append(ev)
        self._narrative_evolver.after_narrative_recorded(ev)
        return ev

    def build_life_context(self, days: int = 1) -> LifeContextInput:
        date_str = datetime.now(timezone.utc).date().isoformat()
        ledger_entries = timeline_entries_recent(self._ledger_log, days=days)
        return self._narrative_evolver.build_life_context(
            ledger_entries,
            days=days,
            date_str=date_str,
        )

    def record_turn(
        self,
        question: str,
        answer: str,
        session_id: str = "tao",
        salience: float = 0.3,
    ) -> None:
        """将一次完成的用户对话回合下发至 LifeService 异步处理。"""
        self._turn_index += 1
        self._life_service.enqueue_user_turn(
            session_id=session_id,
            turn_index=self._turn_index,
            user_text=question,
            agent_reply=answer,
            salience=salience,
        )

    def record_scheduler_digest_from_heartbeat(self, tasks_text: str) -> LedgerEvent | None:
        return append_scheduler_digest(self._ledger_log, tasks_text)

    def receive_experience(self, result: MemoryHeartbeatResult) -> None:
        hint = (result.signal.narrative_hint or "").strip()
        if hint:
            ev = NarrativeEvent.now(
                NarrativeEventKind.THOUGHT,
                f"心跳反刍线索：{hint}",
                source="heartbeat_wander",
                heartbeat_tick_id=result.tick_id,
            )
            self._narrative_log.append(ev)
            self._life_service.enqueue_story_beat(
                narrative_hint=f"心跳反刍线索：{hint}",
                salience=min(result.signal.intensity * 0.6, 0.8),
                arousal_delta=result.signal.intensity * 0.15,
            )
        if result.signal.intensity >= 0.55:
            dom = result.signal.dominant_emotion or "—"
            ev = NarrativeEvent.now(
                NarrativeEventKind.MILESTONE,
                f"心跳漂移节点：烈度 {result.signal.intensity:.2f}，主导情绪 {dom}",
                source="heartbeat_wander",
                heartbeat_tick_id=result.tick_id,
            )
            self._narrative_log.append(ev)
            self._narrative_evolver.after_narrative_recorded(ev)
            self._life_service.enqueue_story_beat(
                narrative_hint=f"心跳漂移节点：烈度 {result.signal.intensity:.2f}，主导情绪 {dom}",
                emotion_label=dom,
                valence_delta=result.signal.intensity * -0.1,
                arousal_delta=result.signal.intensity * 0.2,
                salience=result.signal.intensity,
                action_kind=ExperienceActionKind.deciding,
            )

    def get_event_by_id(self, event_id: str) -> LedgerEvent | NarrativeEvent | None:
        le = self._ledger_log.get_by_id(event_id)
        if le is not None:
            return le
        return self._narrative_log.get_by_id(event_id)

    def advance_story(self, title: str, phase: StoryPhase) -> None:
        self._narrative_evolver.advance_chapter(title=title, phase=phase)

    def load_profile(self) -> LifeProfile:
        stored = self._profile_store.load()
        if not stored.is_stale():
            self._profile = stored
        if self._profile.narrative:
            self._life_service.update_context(profile_narrative=self._profile.narrative)
        return self._profile

    def run_daily_review(
        self,
        static_profile: PersonaProfile,
        today_medium_term: str = "",
        today_scheduler_tasks: str = "",
        scheduler_engine=None,
    ) -> tuple[DailySynthesisResult, LifeContextInput] | None:
        if self._synthesizer is None:
            return None

        dialogue_count = count_dialogue_recent(self._ledger_log, days=7)
        detected_phase = self._narrative_evolver.detect_phase(dialogue_count, recent_days=7)
        if detected_phase != self._narrative_evolver.current_phase:
            self._narrative_evolver.advance_chapter(
                title=f"进入{detected_phase.value}阶段",
                phase=detected_phase,
            )

        result = self._synthesizer.run(
            static_profile=static_profile,
            today_medium_term=today_medium_term,
            today_scheduler_tasks=today_scheduler_tasks,
            narrative_event_log=self._narrative_log,
            story_phase=self._narrative_evolver.current_phase.value,
        )

        life_ctx = self.build_life_context(days=1)
        for t in result.thought_records:
            if t.strip():
                life_ctx.notable_flags.append(f"[thought] {t.strip()}")

        if scheduler_engine is not None and result.scheduler_actions:
            self._schedule_actions(result.scheduler_actions, scheduler_engine)

        if self._profile_generator is not None:
            digest = format_timeline_digest_for_profile(
                timeline_entries_recent(self._ledger_log, days=30),
                self._narrative_log.recent(days=30),
                tail=20,
            )
            new_profile = self._profile_generator.generate(
                static_profile=static_profile,
                timeline_digest=digest,
                medium_term_distillate=today_medium_term,
            )
            self._profile = new_profile
            self._profile_store.save(new_profile)

            # 反思闭环：将新画像的叙事自述回写到手账，供明日编排地标时参考
            if new_profile.narrative:
                self._journal.set_narrative(new_profile.narrative)
                self._journal_store.save(self._journal)
                self._life_service.update_context(profile_narrative=new_profile.narrative)

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
