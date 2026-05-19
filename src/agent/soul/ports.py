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
