from __future__ import annotations

from datetime import datetime, timezone

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


class LifeManager:
    """Life 入口：只 delegating 到 ``ledger`` 与 ``narrative``；演化何时跑由 heartbeat 等上层触发。"""

    def __init__(
        self,
        life_dir: str,
        llm: BaseLLM | None = None,
    ) -> None:
        self._llm = llm

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
