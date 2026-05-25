from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from infra.llm import BaseLLM

if TYPE_CHECKING:
    from agent.soul.handlers.tao.types import TaoRunRequest, TaoRunResult


class LLMServicePort(Protocol):
    """infra LLMService 面向 Soul 的最小接口。"""

    def get_aux_llm(self, name: str) -> BaseLLM | None: ...


class BaseTaoServicePort(Protocol):
    """Base Tao 推理服务：走完整 ReAct 链，与模块 LLM 直调分离。"""

    def run(self, request: TaoRunRequest) -> TaoRunResult: ...


class ExternalOpportunitySupplier(Protocol):
    """顶层外界时机探测接口（可为空实现）。"""

    def is_opportune(
        self,
        *,
        session_id: str,
        impulse_level: float,
        expectation: str,
    ) -> bool: ...


class EmbeddingPort(Protocol):
    """顶层 embedding 服务最小接口。"""

    def embed(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
