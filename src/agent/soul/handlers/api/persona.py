from __future__ import annotations

from typing import TYPE_CHECKING, Any

from config.agent.persona_config import PersonaConfig
from infra.llm import BaseLLM

from agent.soul.ports import LLMServicePort
from agent.soul.persona.manager import PersonaManager
from agent.soul.persona.service import PersonaService

from ._llm import resolve_module_llm
from .actions import PersonaAction

if TYPE_CHECKING:
    from agent.soul.workers import DomainWorker

__all__ = ["PersonaAction", "PersonaHandler"]


class PersonaHandler:
    """Persona API：只读查询 + profile 管理 + 月度漂移（唯一 self_concept 演化入口）。"""

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
        self._service: PersonaService | None = None
        self._worker: DomainWorker | None = None
        self._memory_port = None
        self._embedder = None

    def set_worker(self, worker: DomainWorker) -> None:
        self._worker = worker
        if self._service is not None:
            self._service.set_worker(worker)

    def set_memory_port(self, port) -> None:
        self._memory_port = port
        if self._service is not None:
            self._service.set_memory_port(port)

    def set_embedder(self, embedder) -> None:
        self._embedder = embedder
        if self._service is not None:
            self._service.set_embedder(embedder)

    def resolve_llm(self) -> BaseLLM | None:
        return resolve_module_llm(
            self._llm_service, self._llm_aux_name, self._primary_llm
        )

    @property
    def service(self) -> PersonaService:
        return self._ensure_service()

    def _ensure_service(self) -> PersonaService:
        if self._service is None:
            manager = PersonaManager(self._cfg, llm=self.resolve_llm())
            self._service = PersonaService(manager)
            if self._worker is not None:
                self._service.set_worker(self._worker)
            if self._memory_port is not None:
                self._service.set_memory_port(self._memory_port)
            if self._embedder is not None:
                self._service.set_embedder(self._embedder)
        return self._service

    def handle(self, action: str, payload: dict[str, Any]) -> Any:
        svc = self._ensure_service()

        if action == PersonaAction.RESET_SELF_CONCEPT:
            svc.reset_self_concept()
            return {"ok": True, "applied": True, "reason": "reset_self_concept"}

        if action == PersonaAction.GET_SNAPSHOT:
            return svc.snapshot()

        if action == PersonaAction.PORTRAIT_REVISION:
            return svc.portrait_revision()

        if action == PersonaAction.PORTRAIT_FOR_NARRATIVE:
            max_chars = int(payload.get("max_chars", 1200))
            compact = bool(payload.get("compact", False))
            return svc.portrait_for_narrative(max_chars=max_chars, compact=compact)

        if action == PersonaAction.RELOAD_PROFILE:
            return svc.reload_profile()

        if action == PersonaAction.REBUILD_PROFILE:
            preserve_self_concept = bool(payload.get("preserve_self_concept", False))
            return svc.rebuild_profile(preserve_self_concept=preserve_self_concept)

        if action == PersonaAction.GET_BUFFER:
            include_signals = bool(payload.get("include_signals", False))
            return svc.buffer_snapshot(include_signals=include_signals)

        if action == PersonaAction.RUN_MONTHLY_DRIFT:
            force = bool(payload.get("force", False))
            month = str(payload.get("month", ""))
            return svc.run_monthly_drift(force=force, month=month)

        if action == PersonaAction.ENSURE_DISTILL:
            force = bool(payload.get("force", False))
            return svc.ensure_distill(force=force)

        if action == PersonaAction.GET_DISTILL:
            return svc.get_distill()

        raise ValueError(f"unknown persona api action: {action!r}")
