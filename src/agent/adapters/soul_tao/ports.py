from __future__ import annotations

from typing import Protocol

from .types import TaoRunRequest, TaoRunResult


class BaseTaoServicePort(Protocol):
    """Base Tao 推理服务：走完整 ReAct 链，与 Soul 模块 LLM 直调分离。"""

    def run(self, request: TaoRunRequest) -> TaoRunResult: ...
