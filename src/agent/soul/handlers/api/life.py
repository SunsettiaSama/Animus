from __future__ import annotations

from typing import TYPE_CHECKING, Any

from infra.llm import BaseLLM

from agent.soul.ports import LLMServicePort

from ._llm import resolve_module_llm
from .actions import LifeAction

if TYPE_CHECKING:
    from agent.soul.life import LifeManager, NarrativeEngine

__all__ = ["LifeAction", "LifeHandler"]


class LifeHandler:
    """Life API Handler：模块 LLM 直调 + LifeManager。"""

    DEFAULT_AUX_NAME = "life"

    def __init__(
        self,
        life_dir: str,
        llm_service: LLMServicePort | None = None,
        llm_aux_name: str = DEFAULT_AUX_NAME,
        primary_llm: BaseLLM | None = None,
    ) -> None:
        self._life_dir = life_dir
        self._llm_service = llm_service
        self._llm_aux_name = llm_aux_name
        self._primary_llm = primary_llm
        self._manager: LifeManager | None = None

    def resolve_llm(self) -> BaseLLM | None:
        return resolve_module_llm(
            self._llm_service, self._llm_aux_name, self._primary_llm
        )

    @property
    def api(self) -> LifeManager:
        return self._ensure_manager()

    @property
    def narrative(self) -> NarrativeEngine | None:
        return self.api.narrative

    def _ensure_manager(self) -> LifeManager:
        if self._manager is None:
            from agent.soul.life import LifeManager
            self._manager = LifeManager(
                life_dir=self._life_dir,
                llm=self.resolve_llm(),
            )
        return self._manager

    def handle(self, action: str, payload: dict[str, Any]) -> Any:
        manager = self._ensure_manager()

        if action == LifeAction.FABRICATE:
            engine = manager.narrative
            if engine is None:
                raise RuntimeError("Life narrative engine unavailable — no LLM resolved")
            return engine.fabricate(**payload)

        if action == LifeAction.RECORD_TURN:
            raise RuntimeError(
                "record_turn 已迁移至 SoulService.record_dialogue_turn / presence/experience"
            )

        if action == LifeAction.ADD_LANDMARK:
            return manager.add_landmark(**payload)

        if action == LifeAction.LOAD_PROFILE:
            profile = manager.load_profile()
            return profile.to_dict()

        if action == LifeAction.STATUS:
            return manager.service_status()

        if action == LifeAction.COMPOSE_LANDMARK:
            return manager.compose_landmark()

        if action == LifeAction.COUNT_LANDMARKS_SINCE:
            return manager.count_landmarks_written_since(payload["since"])

        if action == LifeAction.TRIGGER_LANDMARKS:
            return manager.trigger_due_landmarks()

        if action == LifeAction.TICK_SURPRISE:
            elapsed = float(payload.get("elapsed_sec", 300.0))
            return manager.tick_surprise(elapsed_sec=elapsed)

        if action == LifeAction.PLAN_LANDMARK:
            raise RuntimeError(
                "plan_landmark is handled by HeartbeatOrchestrator, not LifeHandler"
            )

        if action == LifeAction.RECORD_SCHEDULER_DIGEST:
            manager.record_scheduler_digest_from_heartbeat(payload["tasks_text"])
            return None

        if action == LifeAction.RECENT_CHRONICLE:
            return manager.recent_chronicle(
                days=int(payload.get("days", 7)),
                tail=int(payload.get("tail", 50)),
            )

        if action == LifeAction.HOT_STORAGE:
            hours_raw = payload.get("hours")
            hours = int(hours_raw) if hours_raw is not None else None
            return manager.hot_experiences(hours=hours)

        raise ValueError(f"unknown life action: {action!r}")

    def stop(self) -> None:
        if self._manager is not None:
            self._manager.stop()
