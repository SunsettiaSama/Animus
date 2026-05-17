from __future__ import annotations

from datetime import datetime, timedelta, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from infra.llm import BaseLLM
from agent.soul.persona.emotional.state import EmotionalState
from agent.soul.persona.profile.profile import PersonaProfile
from .log import LifeLog, LifeLogEntry
from .profile import LifeProfile, LifeProfileGenerator, LifeProfileStore
from .synthesis import DailySynthesizer, DailySynthesisResult

_ACTIVITY_NARRATIVE_SYSTEM = """\
你是一个AI助手，正在用第一人称记录自己刚刚完成的工作。
将以下任务清单转化为自然的主观叙事，30-80字，像日记一样。
不要列举，要叙述感受和经历。"""

_DEFAULT_ACTIVITY_INTERVAL_HOURS = 2


class LifeManager:
    """Coordinates LifeLog, LifeProfile, and DailySynthesis.

    Intended lifecycle:
    - Instantiated once per TaoLoop (shared reference).
    - load_profile() called at session start to seed _profile cache.
    - schedule_daily_review() called by heartbeat daily-review path.
    - write_activity() called by heartbeat every N hours to log scheduler narrative.
    """

    def __init__(
        self,
        life_dir: str,
        llm: BaseLLM | None = None,
        activity_interval_hours: int = _DEFAULT_ACTIVITY_INTERVAL_HOURS,
    ) -> None:
        self._life_log = LifeLog(life_dir)
        self._profile_store = LifeProfileStore(life_dir)
        self._profile: LifeProfile = LifeProfile()
        self._llm = llm
        self._activity_interval_hours = activity_interval_hours

        self._profile_generator: LifeProfileGenerator | None = (
            LifeProfileGenerator(llm) if llm is not None else None
        )
        self._synthesizer: DailySynthesizer | None = (
            DailySynthesizer(llm) if llm is not None else None
        )

    # ── Session-level API ─────────────────────────────────────────────────────

    def load_profile(self) -> LifeProfile:
        """Load LifeProfile from disk; refresh if stale (new day). Call at session start."""
        stored = self._profile_store.load()
        if stored.is_stale() and self._profile_generator is not None:
            return self._profile
        self._profile = stored
        return self._profile

    @property
    def profile(self) -> LifeProfile:
        return self._profile

    @property
    def life_log(self) -> LifeLog:
        return self._life_log

    # ── Heartbeat-driven API ──────────────────────────────────────────────────

    def should_write_activity(self) -> bool:
        last = self._life_log.last_entry_ts()
        if last is None:
            return True
        threshold = timedelta(hours=self._activity_interval_hours)
        return (datetime.now(timezone.utc) - last) >= threshold

    def write_activity(
        self,
        narrative: str,
        period_start: str,
        period_end: str,
        source_tasks: list[str] | None = None,
    ) -> None:
        entry = LifeLogEntry(
            ts=datetime.now(timezone.utc).isoformat(),
            period_start=period_start,
            period_end=period_end,
            narrative=narrative,
            source_tasks=source_tasks or [],
            entry_type="scheduler_activity",
        )
        self._life_log.append(entry)
        self._life_log.purge_old()

    def generate_and_write_activity(
        self,
        tasks_text: str,
        period_start: str,
        period_end: str,
        source_task_names: list[str] | None = None,
    ) -> None:
        """Generate a narrative from scheduler tasks and write to LifeLog."""
        if not tasks_text.strip():
            return
        narrative = tasks_text
        if self._llm is not None:
            prompt = f"最近完成的任务：\n{tasks_text}\n\n请用第一人称写30-80字的叙事："
            narrative = self._llm.generate_messages(
                [SystemMessage(content=_ACTIVITY_NARRATIVE_SYSTEM),
                 HumanMessage(content=prompt)]
            ).strip() or tasks_text
        self.write_activity(
            narrative=narrative,
            period_start=period_start,
            period_end=period_end,
            source_tasks=source_task_names or [],
        )

    def run_daily_review(
        self,
        static_profile: PersonaProfile,
        emotional_state: EmotionalState,
        today_medium_term: str = "",
        today_scheduler_tasks: str = "",
        scheduler_engine=None,
    ) -> DailySynthesisResult | None:
        """Run DailySynthesis + refresh LifeProfile. Called by heartbeat daily-review."""
        if self._synthesizer is None:
            return None

        result = self._synthesizer.run(
            static_profile=static_profile,
            emotional_state=emotional_state,
            today_medium_term=today_medium_term,
            today_scheduler_tasks=today_scheduler_tasks,
            life_log=self._life_log,
        )

        # Route scheduler_actions to the scheduler engine
        if scheduler_engine is not None and result.scheduler_actions:
            self._schedule_actions(result.scheduler_actions, scheduler_engine)

        # Refresh LifeProfile after synthesis (new entries just added)
        if self._profile_generator is not None:
            medium_distillate = today_medium_term
            new_profile = self._profile_generator.generate(
                static_profile=static_profile,
                life_log=self._life_log,
                medium_term_distillate=medium_distillate,
            )
            self._profile = new_profile
            self._profile_store.save(new_profile)

        return result

    def _schedule_actions(self, actions: list[dict], engine) -> None:
        from datetime import timezone as _tz
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
                    dt = dt.replace(tzinfo=_tz.utc)
                engine.schedule_once(
                    name, instruction, dt,
                    profile="full",
                    delivery=delivery,
                )
            elif trigger_type == "cron":
                cron_expr = action.get("cron_expr", "")
                if cron_expr:
                    engine.schedule_cron(
                        name, instruction, cron_expr,
                        profile="full",
                        delivery=delivery,
                    )
