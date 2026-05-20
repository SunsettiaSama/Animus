from __future__ import annotations

from typing import Any, Protocol


class RobotDogPort(Protocol):
    """机器狗 / 四足机器人交互通道（占位）。"""

    def attach(self, session_id: str, robot_id: str) -> None: ...

    def submit_motion(self, session_id: str, motion: dict[str, Any]) -> None: ...

    def read_proprioception(self, session_id: str) -> dict[str, Any]: ...

    def detach(self, session_id: str) -> None: ...
