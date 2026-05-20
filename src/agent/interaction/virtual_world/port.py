from __future__ import annotations

from typing import Any, Protocol


class VirtualWorldPort(Protocol):
    """虚拟世界 / 游戏交互通道（占位）。"""

    def bind_world(self, session_id: str, world_id: str) -> None: ...

    def enter_instance(self, session_id: str, instance_id: str) -> None: ...

    def push_game_event(self, session_id: str, event: dict[str, Any]) -> None: ...

    def pull_state_delta(self, session_id: str) -> dict[str, Any]: ...
