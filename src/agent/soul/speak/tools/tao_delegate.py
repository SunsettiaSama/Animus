from __future__ import annotations

from typing import Any, Protocol


class SpeakToolPort(Protocol):
    """Speak 可选语义任务工具口。"""

    def run_semantic_task(self, instruction: str, *, session_id: str = "tao") -> dict[str, Any]: ...


class TaoSpeakToolAdapter:
    """Tao/Loop 降级工具：默认不在主路径启用。"""

    def __init__(self, tao_handler=None) -> None:
        self._tao_handler = tao_handler

    def set_tao_handler(self, tao_handler) -> None:
        self._tao_handler = tao_handler

    def run_semantic_task(
        self,
        instruction: str,
        *,
        session_id: str = "tao",
    ) -> dict[str, Any]:
        if self._tao_handler is None:
            raise RuntimeError("tao_delegate 未接线")
        from agent.soul.handlers.tao.types import TaoRunRequest

        result = self._tao_handler.run(TaoRunRequest(instruction=instruction))
        return {
            "ok": True,
            "session_id": session_id,
            "answer": result.answer,
            "steps": list(result.steps or []),
        }
