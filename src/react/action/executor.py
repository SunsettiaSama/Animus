from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .base import BaseAction

if TYPE_CHECKING:
    pass


class ActionExecutor:
    def __init__(self):
        self._registry: dict[str, type[BaseAction]] = {}

    def register(self, action_cls: type[BaseAction]) -> type[BaseAction]:
        self._registry[action_cls.name] = action_cls
        return action_cls

    def run(self, json_input: str) -> str:
        payload: dict = json.loads(json_input)

        action_name: str = payload["action"]
        args: dict = payload.get("args", {})

        if action_name not in self._registry:
            raise ValueError(f"unknown action: {action_name!r}")

        action = self._registry[action_name]()
        return action.execute(**args)

    @property
    def available_actions(self) -> list[str]:
        return list(self._registry.keys())
