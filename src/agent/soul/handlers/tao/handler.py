from __future__ import annotations

from agent.profile import SubAgentProfile
from agent.soul.ports import BaseTaoServicePort

from .backend import SubAgentTaoBackend
from .types import TaoRunRequest, TaoRunResult


class BaseTaoHandler:
    """Tao Handler：Soul 模块经此发起完整 ReAct 推理。"""

    DEFAULT_PROFILE = "with_memory"

    def __init__(
        self,
        backend: BaseTaoServicePort | None = None,
        llm_cfg_path: str = "config/llm_core/config.yaml",
        profiles: dict[str, SubAgentProfile] | None = None,
        scheduler_engine=None,
        soul=None,
    ) -> None:
        self._soul = soul
        self._backend: BaseTaoServicePort = backend or SubAgentTaoBackend(
            llm_cfg_path=llm_cfg_path,
            profiles=profiles,
            scheduler_engine=scheduler_engine,
            soul=soul,
        )

    def set_backend(self, backend: BaseTaoServicePort) -> None:
        self._backend = backend

    def set_scheduler_engine(self, engine) -> None:
        if isinstance(self._backend, SubAgentTaoBackend):
            self._backend.set_scheduler_engine(engine)

    def run(self, request: TaoRunRequest) -> TaoRunResult:
        return self._backend.run(request)
