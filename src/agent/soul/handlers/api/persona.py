from __future__ import annotations

from typing import TYPE_CHECKING, Any

from config.agent.persona_config import PersonaConfig
from infra.llm import BaseLLM

from agent.soul.ports import LLMServicePort

from ._llm import resolve_module_llm
from .actions import PersonaAction

if TYPE_CHECKING:
    from agent.soul.persona import PersonaManager
    from agent.soul.workers import DomainWorker

__all__ = ["PersonaAction", "PersonaHandler"]


class PersonaHandler:
    """Persona API Handler：模块 LLM 直调 + PersonaManager（不含 Tao 推理）。"""

    DEFAULT_AUX_NAME = "persona"

    def __init__(
        self,
        cfg: PersonaConfig,
        llm_service: LLMServicePort | None = None,
        llm_aux_name: str = DEFAULT_AUX_NAME,
        primary_llm: BaseLLM | None = None,
    ) -> None:
        self._cfg = cfg
        self._llm_service = llm_service
        self._llm_aux_name = llm_aux_name
        self._primary_llm = primary_llm
        self._manager: PersonaManager | None = None
        self._worker: DomainWorker | None = None

    def set_worker(self, worker: DomainWorker) -> None:
        self._worker = worker
        if self._manager is not None:
            self._manager.set_worker(worker)

    def resolve_llm(self) -> BaseLLM | None:
        return resolve_module_llm(
            self._llm_service, self._llm_aux_name, self._primary_llm
        )

    @property
    def api(self) -> PersonaManager:
        return self._ensure_manager()

    def _ensure_manager(self) -> "PersonaManager":
        if self._manager is None:
            from agent.soul.persona import PersonaManager
            self._manager = PersonaManager(
                self._cfg,
                llm=self.resolve_llm(),
            )
            if self._worker is not None:
                self._manager.set_worker(self._worker)
        return self._manager

    def set_tao_handler(self, handler) -> None:
        if self._manager is not None:
            self._manager.set_tao_handler(handler)

    def handle(self, action: str, payload: dict[str, Any]) -> Any:
        manager = self._ensure_manager()

        if action == PersonaAction.EVOLVE:
            manager.evolve(**payload)
            return None

        if action == PersonaAction.CLEAR_DRIFT:
            manager.clear_drift()
            return None

        if action == PersonaAction.EVOLVE_SELF_CONCEPT:
            return manager.evolve_self_concept(**payload)

        if action == PersonaAction.GET_SNAPSHOT:
            return manager.snapshot()

        if action == PersonaAction.RECORD_INTERACTION:
            manager.evolve(
                question=str(payload.get("question", "")),
                answer=str(payload.get("answer", "")),
                steps=payload.get("steps") or [],
                life_context=payload.get("life_context"),
                medium_term_context=str(payload.get("medium_term_context", "")),
            )
            return {"ok": True}

        raise ValueError(f"unknown persona api action: {action!r}")
