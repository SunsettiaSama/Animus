from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .handler import BaseTaoHandler
from .types import TaoRunRequest
from .actions import TaoPersonaAction

if TYPE_CHECKING:
    from agent.soul.handlers.api.persona import PersonaHandler

__all__ = ["TaoPersonaAction", "TaoPersonaHandler"]


class TaoPersonaHandler:
    """Persona Tao Handler：经 Base Tao 完整推理（日终反省等）。"""

    def __init__(
        self,
        tao_handler: BaseTaoHandler,
        persona_api: PersonaHandler,
    ) -> None:
        self._tao_handler = tao_handler
        self._persona_api = persona_api

    def set_tao_handler(self, handler: BaseTaoHandler) -> None:
        self._tao_handler = handler
        self._persona_api.set_tao_handler(handler)

    @property
    def tao(self) -> BaseTaoHandler:
        return self._tao_handler

    def handle(self, action: str, payload: dict[str, Any]) -> Any:
        manager = self._persona_api.api
        manager.set_tao_handler(self._tao_handler)

        if action == TaoPersonaAction.RUN_DAILY_REFLECTION:
            return manager.run_daily_reflection(**payload)

        if action == TaoPersonaAction.RUN:
            req = TaoRunRequest(**payload)
            result = self._tao_handler.run(req)
            return {
                "answer": result.answer,
                "step_count": result.step_count,
                "steps": [
                    {
                        "index": s.index,
                        "thought": s.thought,
                        "action": s.action,
                        "action_input": s.action_input,
                        "observation": s.observation,
                    }
                    for s in result.steps
                ],
            }

        raise ValueError(f"unknown persona tao action: {action!r}")
